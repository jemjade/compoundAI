"""Real Responses-API synthesis, chunking, BM25 retrieval, and grounded-QA runner.

The ``run`` command implements the JSON stdin/stdout contract in ``research.pilot``.  Logs go to
stderr and never include the API key.  ``preflight`` computes calls without contacting a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from research.pilot import CONDITIONS, SAFE_BLOCK_FIELDS, digest, runner_payload

SYNTHESIS_PROMPT_VERSION = "loss-controlled-synthesis-v1"
QA_PROMPT_VERSION = "grounded-qa-json-v1"
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z]+|[가-힣]+")
SOURCE_PATTERN = re.compile(r"\[source:([^\]\n]+)\]")
ALLOWED_PAYLOAD_KEYS = {"schema_version", "repeat_id", "blocks", "questions"}
ALLOWED_BLOCK_KEYS = set(SAFE_BLOCK_FIELDS)

SYNTHESIS_INSTRUCTIONS = """You are producing a loss-controlled intermediate representation.
Preserve every factual statement, number, unit, date, table row, sign, and qualifier from the
source blocks. Do not infer answers and do not omit facts because they seem unimportant. Keep
each paragraph attributable by starting it with one or more exact [source:BLOCK_ID] markers.
Return only the synthesized document text. The input contains no evaluation answer or condition
label."""

QA_INSTRUCTIONS = """Answer the question using only the retrieved chunks. Return exactly one JSON
object with keys answer and evidence_chunk_ids. evidence_chunk_ids must contain only chunk IDs
shown in the input. If the evidence is insufficient, say so in answer and return an empty list.
Do not use outside knowledge. Preserve numeric signs, units, and calculation details."""


class PipelineError(RuntimeError):
    """A fail-closed pipeline error."""


@dataclass(frozen=True)
class RunnerConfig:
    schema_version: int = 1
    provider: str = "openai_responses"
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 120.0
    max_retries: int = 0
    synthesis_batch_chars: int = 90_000
    chunk_chars: int = 5_000
    chunk_overlap_chars: int = 400
    retrieval_top_k: int = 6
    synthesis_max_output_tokens: int = 12_000
    qa_max_output_tokens: int = 1_200
    reasoning_effort: str | None = None
    verbosity: str | None = "low"
    temperature: float | None = None
    top_p: float | None = None
    max_calls_per_pipeline: int = 64

    @classmethod
    def load(cls, path: Path | None) -> RunnerConfig:
        raw: dict[str, Any] = {}
        if path is not None:
            loaded = json.loads(path.read_text())
            if not isinstance(loaded, dict):
                raise ValueError("Runner config must be a JSON object")
            raw.update(loaded)
        if "api_key" in raw:
            raise ValueError("Do not put an API key in config; use api_key_env")
        env_map = {
            "RESEARCH_LLM_PROVIDER": "provider",
            "RESEARCH_LLM_MODEL": "model",
            "RESEARCH_LLM_BASE_URL": "base_url",
            "RESEARCH_LLM_API_KEY_ENV": "api_key_env",
            "RESEARCH_LLM_REASONING_EFFORT": "reasoning_effort",
            "RESEARCH_LLM_VERBOSITY": "verbosity",
        }
        for env_name, field in env_map.items():
            if env_name in os.environ:
                raw[field] = os.environ[env_name]
        numeric_env = {
            "RESEARCH_LLM_TIMEOUT_SECONDS": ("timeout_seconds", float),
            "RESEARCH_LLM_MAX_RETRIES": ("max_retries", int),
            "RESEARCH_SYNTHESIS_BATCH_CHARS": ("synthesis_batch_chars", int),
            "RESEARCH_CHUNK_CHARS": ("chunk_chars", int),
            "RESEARCH_CHUNK_OVERLAP_CHARS": ("chunk_overlap_chars", int),
            "RESEARCH_RETRIEVAL_TOP_K": ("retrieval_top_k", int),
            "RESEARCH_SYNTHESIS_MAX_OUTPUT_TOKENS": (
                "synthesis_max_output_tokens",
                int,
            ),
            "RESEARCH_QA_MAX_OUTPUT_TOKENS": ("qa_max_output_tokens", int),
            "RESEARCH_MAX_CALLS_PER_PIPELINE": ("max_calls_per_pipeline", int),
            "RESEARCH_LLM_TEMPERATURE": ("temperature", float),
            "RESEARCH_LLM_TOP_P": ("top_p", float),
        }
        for env_name, (field, converter) in numeric_env.items():
            if env_name in os.environ:
                raw[field] = converter(os.environ[env_name])
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown runner config keys: {sorted(unknown)}")
        config = cls(**raw)
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != 1 or self.provider != "openai_responses":
            raise ValueError("Only schema_version=1 and provider=openai_responses are supported")
        if self.reasoning_effort == "":
            object.__setattr__(self, "reasoning_effort", None)
        if self.verbosity == "":
            object.__setattr__(self, "verbosity", None)
        if self.reasoning_effort not in {
            None,
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("Unsupported reasoning_effort")
        if self.verbosity not in {None, "low", "medium", "high"}:
            raise ValueError("Unsupported verbosity")
        positive = (
            self.timeout_seconds,
            self.synthesis_batch_chars,
            self.chunk_chars,
            self.retrieval_top_k,
            self.synthesis_max_output_tokens,
            self.qa_max_output_tokens,
            self.max_calls_per_pipeline,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int | float) or value <= 0
            for value in positive
        ):
            raise ValueError("Runner limits must be positive")
        if not math.isfinite(self.timeout_seconds):
            raise ValueError("timeout_seconds must be finite")
        if not 0 <= self.chunk_overlap_chars < self.chunk_chars:
            raise ValueError("chunk_overlap_chars must be nonnegative and smaller than chunk_chars")
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.top_p is not None and not 0 <= self.top_p <= 1:
            raise ValueError("top_p must be between 0 and 1")
        if self.temperature is not None and self.top_p is not None:
            raise ValueError("Set temperature or top_p, not both")
        if not self.api_key_env or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", self.api_key_env):
            raise ValueError("api_key_env must be an environment variable name")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) URL without credentials/query/fragment")

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        parsed = urlsplit(self.base_url)
        value["base_url"] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        value["api_key_configured"] = bool(os.environ.get(self.api_key_env))
        return value


@dataclass(frozen=True)
class Generation:
    text: str
    response_id: str
    model: str
    usage: dict[str, int]
    status: str = "completed"


class Generator(Protocol):
    def generate(
        self,
        *,
        stage: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> Generation: ...


class OpenAIResponsesAdapter:
    """One provider adapter using the official OpenAI Python SDK Responses API."""

    execution_mode = "live_model"

    def __init__(self, config: RunnerConfig, client: Any | None = None) -> None:
        self.config = config
        self.sdk_version = "injected_client"
        if client is None:
            api_key = os.environ.get(config.api_key_env)
            if not api_key:
                raise PipelineError(f"Missing API key environment variable: {config.api_key_env}")
            try:
                import openai
                from openai import OpenAI
            except ImportError as error:
                raise PipelineError(
                    "Install research/requirements.txt to use the live runner"
                ) from error
            self.sdk_version = openai.__version__
            client = OpenAI(
                api_key=api_key,
                base_url=config.base_url,
                timeout=config.timeout_seconds,
                max_retries=config.max_retries,
            )
        self.client = client

    def generate(
        self,
        *,
        stage: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> Generation:
        parameters: dict[str, Any] = {
            "model": self.config.model,
            "instructions": instructions,
            "input": input_text,
            "max_output_tokens": max_output_tokens,
            "store": False,
        }
        if self.config.reasoning_effort is not None:
            parameters["reasoning"] = {"effort": self.config.reasoning_effort}
        text_config: dict[str, Any] = {}
        if self.config.verbosity is not None:
            text_config["verbosity"] = self.config.verbosity
        if stage == "qa":
            text_config["format"] = {
                "type": "json_schema",
                "name": "grounded_answer",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string"},
                        "evidence_chunk_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["answer", "evidence_chunk_ids"],
                    "additionalProperties": False,
                },
            }
        if text_config:
            parameters["text"] = text_config
        if self.config.temperature is not None:
            parameters["temperature"] = self.config.temperature
        if self.config.top_p is not None:
            parameters["top_p"] = self.config.top_p
        try:
            response = self.client.responses.create(**parameters)
        except Exception as error:
            raise PipelineError(f"{stage} model request failed: {type(error).__name__}") from error
        status = str(getattr(response, "status", ""))
        text = str(getattr(response, "output_text", "") or "")
        if status != "completed" or not text.strip():
            raise PipelineError(f"{stage} model response was {status or 'missing'} or empty")
        usage_obj = getattr(response, "usage", None)
        usage = {
            key: int(getattr(usage_obj, key, 0) or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
        return Generation(
            text=text,
            response_id=str(getattr(response, "id", "")),
            model=str(getattr(response, "model", self.config.model)),
            usage=usage,
            status=status,
        )


def _validate_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or set(payload) != ALLOWED_PAYLOAD_KEYS:
        raise ValueError("Runner accepts only schema_version, repeat_id, blocks, and questions")
    if payload.get("schema_version") != 1 or type(payload.get("repeat_id")) is not int:
        raise ValueError("Invalid runner schema_version or repeat_id")
    blocks = payload.get("blocks")
    questions = payload.get("questions")
    if (
        not isinstance(blocks, list)
        or not blocks
        or not isinstance(questions, list)
        or not questions
    ):
        raise ValueError("Runner needs nonempty blocks and questions")
    block_ids = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("Each block must be an object")
        if set(block) - ALLOWED_BLOCK_KEYS:
            raise ValueError("A block contains fields outside the runner allowlist")
        required = ("block_id", "document_id", "page_number", "text")
        if any(key not in block for key in required):
            raise ValueError("A block is missing a required field")
        if not all(isinstance(block[key], str) for key in ("block_id", "document_id", "text")):
            raise ValueError("Block identifiers and text must be strings")
        if type(block["page_number"]) is not int or block["page_number"] < 1:
            raise ValueError("Block page_number must be a positive integer")
        if "run_id" in block and not isinstance(block["run_id"], str):
            raise ValueError("Block run_id must be a string")
        block_ids.append(block["block_id"])
    if len(block_ids) != len(set(block_ids)):
        raise ValueError("Duplicate block IDs")
    question_ids = []
    document_ids = {block["document_id"] for block in blocks}
    for question in questions:
        if set(question) != {"question_id", "document_id", "question"}:
            raise ValueError("Questions may contain only IDs and question text")
        if not all(isinstance(value, str) for value in question.values()):
            raise ValueError("Question fields must be strings")
        if question["document_id"] not in document_ids:
            raise ValueError("Question document_id has no input blocks")
        question_ids.append(question["question_id"])
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Duplicate question IDs")


def _source_segments(blocks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for block in blocks:
        text = block["text"]
        if not text:
            segments.append({"block": block, "start": 0, "end": 0, "text": ""})
            continue
        for start in range(0, len(text), limit):
            end = min(len(text), start + limit)
            segments.append({"block": block, "start": start, "end": end, "text": text[start:end]})
    return segments


def synthesis_batches(blocks: list[dict[str, Any]], limit: int) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for segment in _source_segments(blocks, limit):
        overhead = 180 + len(segment["block"]["block_id"])
        size = len(segment["text"]) + overhead
        if current and current_chars + size > limit:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _synthesis_input(batch: list[dict[str, Any]]) -> str:
    rows = []
    for segment in batch:
        block = segment["block"]
        header = {
            key: block[key]
            for key in (
                "block_id",
                "document_id",
                "run_id",
                "page_number",
                "canonical_block_id",
                "bbox",
            )
            if key in block
        }
        header["text_start"] = segment["start"]
        header["text_end"] = segment["end"]
        rows.append(f"SOURCE {json.dumps(header, ensure_ascii=False)}\n{segment['text']}")
    return "\n\n".join(rows)


def _chunk_text(text: str, size: int, overlap: int) -> list[tuple[int, int, str]]:
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary
        chunks.append((start, end, text[start:end]))
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]


def bm25_search(query: str, chunks: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    tokenized = [tokenize(chunk["text"]) for chunk in chunks]
    query_tokens = tokenize(query)
    document_count = len(chunks)
    average_length = sum(map(len, tokenized)) / document_count if document_count else 0.0
    document_frequency = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    scored = []
    for chunk, tokens in zip(chunks, tokenized, strict=True):
        frequencies = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            frequency = frequencies[token]
            if not frequency:
                continue
            inverse = math.log(
                1 + (document_count - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * len(tokens) / (average_length or 1.0)
            )
            score += inverse * frequency * 2.5 / denominator
        scored.append({**chunk, "score": round(score, 8)})
    scored.sort(key=lambda row: (-row["score"], row["chunk_id"]))
    return scored[: min(top_k, len(scored))]


def _parse_qa(text: str, valid_chunk_ids: set[str]) -> tuple[str, list[str]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise PipelineError("QA response was not one valid JSON object") from error
    if not isinstance(value, dict) or set(value) != {"answer", "evidence_chunk_ids"}:
        raise PipelineError("QA response must contain only answer and evidence_chunk_ids")
    if not isinstance(value["answer"], str) or not value["answer"].strip():
        raise PipelineError("QA answer is missing")
    evidence = value["evidence_chunk_ids"]
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise PipelineError("QA evidence_chunk_ids must be a string array")
    if len(evidence) != len(set(evidence)) or set(evidence) - valid_chunk_ids:
        raise PipelineError("QA cited duplicate or unavailable chunks")
    return value["answer"], evidence


def _usage_total(generations: list[Generation]) -> dict[str, int]:
    return {
        key: sum(generation.usage.get(key, 0) for generation in generations)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }


def _code_provenance() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    files = [root / "research/pipeline_runner.py", root / "research/pilot.py"]
    file_hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files
    }
    combined_hash = digest(file_hashes)
    git_commit = None
    git_dirty = None
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        git_commit = commit.stdout.strip() or None
        git_dirty = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "code_sha256": combined_hash,
        "code_files_sha256": file_hashes,
        "git_commit": git_commit,
        "git_tracked_files_dirty": git_dirty,
    }


def run_pipeline(
    payload: dict[str, Any], config: RunnerConfig, generator: Generator | None = None
) -> dict[str, Any]:
    config.validate()
    _validate_payload(payload)
    if not config.model:
        raise ValueError("Set model in config or RESEARCH_LLM_MODEL")
    batches = synthesis_batches(payload["blocks"], config.synthesis_batch_chars)
    expected_calls = len(batches) + len(payload["questions"])
    if expected_calls > config.max_calls_per_pipeline:
        raise PipelineError(
            f"Expected {expected_calls} calls exceeds max_calls_per_pipeline="
            f"{config.max_calls_per_pipeline}"
        )
    if generator is None:
        generator = OpenAIResponsesAdapter(config)
    execution_id = str(uuid4())
    started_at = datetime.now(UTC).isoformat()
    trace: list[dict[str, Any]] = []
    generations: list[Generation] = []
    synthesized: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []

    for index, batch in enumerate(batches):
        input_text = _synthesis_input(batch)
        generation = generator.generate(
            stage="synthesis",
            instructions=SYNTHESIS_INSTRUCTIONS,
            input_text=input_text,
            max_output_tokens=config.synthesis_max_output_tokens,
        )
        generations.append(generation)
        source_ids = list(dict.fromkeys(item["block"]["block_id"] for item in batch))
        synthesis_id = f"synthesis:{execution_id}:{index}"
        synthesis_node = {
            "synthesis_id": synthesis_id,
            "text": generation.text,
            "source_block_ids": source_ids,
        }
        synthesized.append(synthesis_node)
        trace.append(
            {
                "stage": "synthesis",
                "input_ids": source_ids,
                "input_text": input_text,
                "input_sha256": hashlib.sha256(input_text.encode()).hexdigest(),
                "output_id": synthesis_id,
                "output_text": generation.text,
                "output_sha256": hashlib.sha256(generation.text.encode()).hexdigest(),
                "source_spans": [
                    {
                        "block_id": item["block"]["block_id"],
                        "start": item["start"],
                        "end": item["end"],
                    }
                    for item in batch
                ],
                "provider_response_id": generation.response_id,
                "model": generation.model,
                "usage": generation.usage,
                "status": generation.status,
            }
        )
        output_chunks = []
        for chunk_index, (start, end, text) in enumerate(
            _chunk_text(generation.text, config.chunk_chars, config.chunk_overlap_chars)
        ):
            referenced = [item for item in SOURCE_PATTERN.findall(text) if item in source_ids]
            chunk_sources = list(dict.fromkeys(referenced)) or source_ids
            chunk = {
                "chunk_id": f"chunk:{execution_id}:{index}:{chunk_index}",
                "parent_synthesis_id": synthesis_id,
                "source_block_ids": chunk_sources,
                "lineage_mode": (
                    "explicit_source_markers" if referenced else "synthesis_batch_fallback"
                ),
                "start": start,
                "end": end,
                "text": text,
            }
            chunks.append(chunk)
            output_chunks.append(chunk)
        trace.append(
            {
                "stage": "chunking",
                "input_ids": [synthesis_id],
                "input_text": generation.text,
                "output": output_chunks,
            }
        )
    if not chunks:
        raise PipelineError("Synthesis produced no searchable chunks")

    answers = []
    for question in payload["questions"]:
        retrieved = bm25_search(question["question"], chunks, config.retrieval_top_k)
        retrieval_output = [
            {
                key: row[key]
                for key in (
                    "chunk_id",
                    "parent_synthesis_id",
                    "source_block_ids",
                    "lineage_mode",
                    "score",
                    "text",
                )
            }
            for row in retrieved
        ]
        trace.append(
            {
                "stage": "retrieval",
                "question_id": question["question_id"],
                "input": {
                    "query": question["question"],
                    "chunk_ids": [chunk["chunk_id"] for chunk in chunks],
                },
                "output": retrieval_output,
            }
        )
        qa_input = json.dumps(
            {"question": question["question"], "retrieved_chunks": retrieval_output},
            ensure_ascii=False,
        )
        generation = generator.generate(
            stage="qa",
            instructions=QA_INSTRUCTIONS,
            input_text=qa_input,
            max_output_tokens=config.qa_max_output_tokens,
        )
        generations.append(generation)
        answer, evidence_chunk_ids = _parse_qa(
            generation.text, {row["chunk_id"] for row in retrieved}
        )
        by_id = {row["chunk_id"]: row for row in retrieved}
        evidence_block_ids = list(
            dict.fromkeys(
                block_id
                for chunk_id in evidence_chunk_ids
                for block_id in by_id[chunk_id]["source_block_ids"]
            )
        )
        answers.append(
            {
                "question_id": question["question_id"],
                "answer": answer,
                "evidence_block_ids": evidence_block_ids,
                "evidence_chunk_ids": evidence_chunk_ids,
            }
        )
        trace.append(
            {
                "stage": "qa",
                "question_id": question["question_id"],
                "input_ids": [row["chunk_id"] for row in retrieved],
                "input_text": qa_input,
                "input_sha256": hashlib.sha256(qa_input.encode()).hexdigest(),
                "output": {
                    "answer": answer,
                    "evidence_chunk_ids": evidence_chunk_ids,
                    "evidence_block_ids": evidence_block_ids,
                },
                "raw_output": generation.text,
                "provider_response_id": generation.response_id,
                "model": generation.model,
                "usage": generation.usage,
                "status": generation.status,
            }
        )

    code_provenance = _code_provenance()
    metadata = {
        "status": "completed",
        "execution_mode": getattr(generator, "execution_mode", "test_or_custom_generator"),
        "pipeline_execution_id": execution_id,
        "provider": config.provider,
        "requested_model": config.model,
        "response_models": sorted({generation.model for generation in generations}),
        "prompt_versions": {
            "synthesis": SYNTHESIS_PROMPT_VERSION,
            "qa": QA_PROMPT_VERSION,
        },
        "prompt_sha256": {
            "synthesis": hashlib.sha256(SYNTHESIS_INSTRUCTIONS.encode()).hexdigest(),
            "qa": hashlib.sha256(QA_INSTRUCTIONS.encode()).hexdigest(),
        },
        "applied_generation_settings": {
            "store": False,
            "reasoning_effort": config.reasoning_effort,
            "verbosity": config.verbosity,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "qa_response_format": "strict_json_schema",
            "synthesis_max_output_tokens": config.synthesis_max_output_tokens,
            "qa_max_output_tokens": config.qa_max_output_tokens,
        },
        "sdk": "openai-python",
        "sdk_version": getattr(generator, "sdk_version", None),
        "runner_config": config.public_dict(),
        "input_sha256": digest(payload),
        **code_provenance,
        "call_count": len(generations),
        "usage": _usage_total(generations),
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "source_kinds": sorted(
            {block.get("source_kind", "unspecified") for block in payload["blocks"]}
        ),
        "synthesis_count": len(synthesized),
        "chunk_count": len(chunks),
    }
    return {"answers": answers, "metadata": metadata, "trace": trace}


def preflight(case: dict[str, Any], config: RunnerConfig, repeats: int) -> dict[str, Any]:
    config.validate()
    if repeats < 1:
        raise ValueError("repeats must be positive")
    rows = []
    total = 0
    total_max_output_tokens = 0
    for repeat in range(repeats):
        for condition, repairs in CONDITIONS.items():
            payload = runner_payload(case, repairs, repeat)
            batches = len(synthesis_batches(payload["blocks"], config.synthesis_batch_chars))
            questions = len(payload["questions"])
            calls = batches + questions
            max_output_tokens = (
                batches * config.synthesis_max_output_tokens
                + questions * config.qa_max_output_tokens
            )
            rows.append(
                {
                    "repeat_id": repeat,
                    "condition": condition,
                    "synthesis_calls": batches,
                    "qa_calls": questions,
                    "total_calls": calls,
                    "max_output_tokens": max_output_tokens,
                    "input_characters": sum(len(block["text"]) for block in payload["blocks"]),
                }
            )
            total += calls
            total_max_output_tokens += max_output_tokens
    return {
        "schema_version": 1,
        "execution_mode": "preflight_no_model_calls",
        "pipeline_runs": repeats * len(CONDITIONS),
        "estimated_model_calls": total,
        "max_output_tokens_if_every_call_hits_limit": total_max_output_tokens,
        "model": config.model or None,
        "config": config.public_dict(),
        "conditions": rows,
    }


def _read_stdin_payload() -> dict[str, Any]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict):
        raise ValueError("stdin must contain one JSON object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--config", type=Path)
    estimate = subparsers.add_parser("preflight")
    estimate.add_argument("--case", type=Path, required=True)
    estimate.add_argument("--config", type=Path)
    estimate.add_argument("--repeats", type=int, default=1)
    estimate.add_argument("--max-total-calls", type=int)
    args = parser.parse_args()
    config = RunnerConfig.load(args.config)
    if args.action == "run":
        response = run_pipeline(_read_stdin_payload(), config)
        print(json.dumps(response, ensure_ascii=False))
        return
    case = json.loads(args.case.read_text())
    report = preflight(case, config, args.repeats)
    allowed = args.max_total_calls
    report["max_total_calls"] = allowed
    report["within_call_budget"] = allowed is None or report["estimated_model_calls"] <= allowed
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["within_call_budget"]:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, PipelineError) as error:
        print(f"Pipeline runner stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
