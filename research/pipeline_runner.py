"""Local Ollama or OpenAI synthesis, chunking, BM25 retrieval, and grounded-QA runner.

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
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from research.pilot import CONDITIONS, SAFE_BLOCK_FIELDS, digest, runner_payload

SYNTHESIS_PROMPT_VERSION = "loss-controlled-synthesis-v1"
PASSTHROUGH_VERSION = "deterministic-block-passthrough-v1"
QA_PROMPT_VERSION = "grounded-qa-json-v1"
QUANTITATIVE_QA_PROMPT_VERSION = "grounded-qa-quantitative-json-v2"
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z]+|[가-힣]+")
SOURCE_PATTERN = re.compile(r"\[source:([^\]\n]+)\]")
ALLOWED_PAYLOAD_KEYS = {"schema_version", "repeat_id", "blocks", "questions"}
ALLOWED_BLOCK_KEYS = set(SAFE_BLOCK_FIELDS)
SUPPORTED_PROVIDERS = {"openai_responses", "ollama_generate"}

QA_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "evidence_chunk_ids": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
    },
    "required": ["answer", "evidence_chunk_ids"],
    "additionalProperties": False,
}

QUANTITATIVE_QA_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "conclusion": {"type": "string"},
        "quantitative_explanation": {"type": "string"},
        "calculations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "evidence_chunk_ids": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
    },
    "required": [
        "conclusion",
        "quantitative_explanation",
        "calculations",
        "evidence_chunk_ids",
    ],
    "additionalProperties": False,
}
SUPPORTED_QA_OUTPUT_CONTRACTS = {"concise_v1", "quantitative_v2"}

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

QUANTITATIVE_QA_INSTRUCTIONS = """Answer the question using only the retrieved chunks. Return
exactly one JSON object with keys conclusion, quantitative_explanation, calculations, and
evidence_chunk_ids. State a direct conclusion. For a quantitative or comparative question,
quantitative_explanation must state the material values used with their periods, signs, and units;
calculations must show the formula or comparison and substituted values needed to support the
conclusion. evidence_chunk_ids must contain only chunk IDs shown in the input. If the evidence is
insufficient, identify what is missing, do not invent a value, and return an empty evidence list
unless a cited chunk directly supports that insufficiency assessment. Do not use outside
knowledge."""


def _qa_contract(contract: str) -> tuple[str, str, dict[str, Any]]:
    if contract == "concise_v1":
        return QA_PROMPT_VERSION, QA_INSTRUCTIONS, QA_RESPONSE_SCHEMA
    if contract == "quantitative_v2":
        return (
            QUANTITATIVE_QA_PROMPT_VERSION,
            QUANTITATIVE_QA_INSTRUCTIONS,
            QUANTITATIVE_QA_RESPONSE_SCHEMA,
        )
    raise ValueError(f"Unsupported qa_output_contract: {contract}")


def _qa_response_schema(
    input_text: str, contract: str = "concise_v1"
) -> dict[str, Any]:
    _, _, base_schema = _qa_contract(contract)
    schema = {
        **base_schema,
        "properties": {
            **base_schema["properties"],
            "evidence_chunk_ids": {
                **base_schema["properties"]["evidence_chunk_ids"],
                "items": {"type": "string"},
            },
        },
    }
    try:
        value = json.loads(input_text)
        rows = value["retrieved_chunks"]
        chunk_ids = [row["chunk_id"] for row in rows]
    except (json.JSONDecodeError, KeyError, TypeError):
        return schema
    if chunk_ids and all(isinstance(chunk_id, str) for chunk_id in chunk_ids):
        schema["properties"]["evidence_chunk_ids"]["items"]["enum"] = list(
            dict.fromkeys(chunk_ids)
        )
    return schema


class PipelineError(RuntimeError):
    """A fail-closed pipeline error."""


@dataclass(frozen=True)
class RunnerConfig:
    schema_version: int = 1
    provider: str = "openai_responses"
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str | None = "OPENAI_API_KEY"
    timeout_seconds: float = 120.0
    max_retries: int = 0
    synthesis_mode: str = "model"
    synthesis_batch_chars: int = 90_000
    chunk_chars: int = 5_000
    chunk_overlap_chars: int = 400
    retrieval_top_k: int = 6
    synthesis_max_output_tokens: int = 12_000
    qa_max_output_tokens: int = 1_200
    qa_output_contract: str = "concise_v1"
    reasoning_effort: str | None = None
    verbosity: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_calls_per_pipeline: int = 64
    ollama_num_ctx: int | None = None
    ollama_keep_alive: str | int | None = None

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
            "RESEARCH_SYNTHESIS_MODE": "synthesis_mode",
            "RESEARCH_QA_OUTPUT_CONTRACT": "qa_output_contract",
            "RESEARCH_OLLAMA_KEEP_ALIVE": "ollama_keep_alive",
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
            "RESEARCH_OLLAMA_NUM_CTX": ("ollama_num_ctx", int),
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
        if self.schema_version != 1 or self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                "Only schema_version=1 and providers openai_responses/ollama_generate are supported"
            )
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
        if self.synthesis_mode not in {"model", "passthrough"}:
            raise ValueError("synthesis_mode must be model or passthrough")
        if self.qa_output_contract not in SUPPORTED_QA_OUTPUT_CONTRACTS:
            raise ValueError("qa_output_contract must be concise_v1 or quantitative_v2")
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
            raise ValueError(
                "chunk_overlap_chars must be nonnegative and smaller than chunk_chars"
            )
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        if self.ollama_num_ctx is not None and (
            type(self.ollama_num_ctx) is not int or self.ollama_num_ctx <= 0
        ):
            raise ValueError("ollama_num_ctx must be a positive integer")
        if self.ollama_keep_alive is not None and (
            isinstance(self.ollama_keep_alive, bool)
            or not isinstance(self.ollama_keep_alive, str | int)
            or (
                isinstance(self.ollama_keep_alive, str)
                and not self.ollama_keep_alive.strip()
            )
        ):
            raise ValueError(
                "ollama_keep_alive must be a duration string or integer seconds"
            )
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.top_p is not None and not 0 <= self.top_p <= 1:
            raise ValueError("top_p must be between 0 and 1")
        if self.temperature is not None and self.top_p is not None:
            raise ValueError("Set temperature or top_p, not both")
        if self.provider == "openai_responses" and (
            not self.api_key_env
            or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", self.api_key_env)
        ):
            raise ValueError("api_key_env must be an environment variable name")
        if self.provider == "ollama_generate" and self.api_key_env is not None:
            raise ValueError("Local Ollama must use api_key_env=null")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "base_url must be an HTTP(S) URL without credentials/query/fragment"
            )
        if self.provider == "ollama_generate" and (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Local Ollama base_url must be an HTTP loopback origin")
        if self.provider == "ollama_generate" and (
            self.reasoning_effort is not None or self.verbosity is not None
        ):
            raise ValueError("Ollama does not accept reasoning_effort or verbosity")

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        parsed = urlsplit(self.base_url)
        value["base_url"] = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", "")
        )
        value["api_key_configured"] = bool(
            self.api_key_env and os.environ.get(self.api_key_env)
        )
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
    sdk = "openai-python"

    def __init__(self, config: RunnerConfig, client: Any | None = None) -> None:
        self.config = config
        self.sdk_version = "injected_client"
        if client is None:
            api_key = os.environ.get(config.api_key_env or "")
            if not api_key:
                raise PipelineError(
                    f"Missing API key environment variable: {config.api_key_env}"
                )
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
                "schema": _qa_response_schema(
                    input_text, self.config.qa_output_contract
                ),
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
            raise PipelineError(
                f"{stage} model request failed: {type(error).__name__}"
            ) from error
        status = str(getattr(response, "status", ""))
        text = str(getattr(response, "output_text", "") or "")
        if status != "completed" or not text.strip():
            raise PipelineError(
                f"{stage} model response was {status or 'missing'} or empty"
            )
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


OllamaTransport = Callable[[str, dict[str, Any], float], dict[str, Any]]


def _request_json(
    url: str,
    *,
    timeout: float,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback is validated
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("Ollama returned a non-object JSON response")
    return result


class OllamaGenerateAdapter:
    """Local-only Ollama native generate API adapter with structured QA output."""

    execution_mode = "live_local_model"
    sdk = "ollama-native-http"

    def __init__(
        self,
        config: RunnerConfig,
        transport: OllamaTransport | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or self._post
        self.last_raw_response: dict[str, Any] | None = None
        if transport is None:
            runtime_metadata = self._discover_runtime()
        self.provider_runtime = runtime_metadata or {"transport": "injected"}
        self.sdk_version = str(self.provider_runtime.get("ollama_version", "unknown"))

    @property
    def _origin(self) -> str:
        return self.config.base_url.rstrip("/")

    def _discover_runtime(self) -> dict[str, Any]:
        try:
            version = _request_json(
                f"{self._origin}/api/version",
                timeout=self.config.timeout_seconds,
            )
            tags = _request_json(
                f"{self._origin}/api/tags",
                timeout=self.config.timeout_seconds,
            )
        except Exception as error:
            raise PipelineError(
                f"Ollama runtime discovery failed: {type(error).__name__}"
            ) from error
        models = tags.get("models")
        if not isinstance(models, list):
            raise PipelineError("Ollama model list is missing")
        selected = next(
            (
                row
                for row in models
                if isinstance(row, dict)
                and self.config.model in {row.get("name"), row.get("model")}
            ),
            None,
        )
        if selected is None:
            raise PipelineError(f"Ollama model is not installed: {self.config.model}")
        details = (
            selected.get("details") if isinstance(selected.get("details"), dict) else {}
        )
        return {
            "ollama_version": str(version.get("version", "unknown")),
            "model_digest": selected.get("digest"),
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
        }

    def _post(
        self, url: str, payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return _request_json(url, timeout=timeout, payload=payload)

    def generate(
        self,
        *,
        stage: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> Generation:
        response_schema = (
            _qa_response_schema(input_text, self.config.qa_output_contract)
            if stage == "qa"
            else None
        )
        return self.generate_with_schema(
            stage=stage,
            instructions=instructions,
            input_text=input_text,
            max_output_tokens=max_output_tokens,
            response_schema=response_schema,
        )

    def generate_with_schema(
        self,
        *,
        stage: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> Generation:
        options: dict[str, Any] = {"num_predict": max_output_tokens}
        if self.config.ollama_num_ctx is not None:
            options["num_ctx"] = self.config.ollama_num_ctx
        if self.config.temperature is not None:
            options["temperature"] = self.config.temperature
        if self.config.top_p is not None:
            options["top_p"] = self.config.top_p
        payload: dict[str, Any] = {
            "model": self.config.model,
            "system": instructions,
            "prompt": input_text,
            "stream": False,
            "options": options,
        }
        if self.config.ollama_keep_alive is not None:
            payload["keep_alive"] = self.config.ollama_keep_alive
        if response_schema is not None:
            payload["format"] = response_schema

        response: dict[str, Any] | None = None
        last_error: Exception | None = None
        self.last_raw_response = None
        for _ in range(self.config.max_retries + 1):
            try:
                response = self.transport(
                    f"{self._origin}/api/generate",
                    payload,
                    self.config.timeout_seconds,
                )
                self.last_raw_response = response
                break
            except Exception as error:
                last_error = error
        if response is None:
            raise PipelineError(
                f"{stage} Ollama request failed: {type(last_error).__name__}"
            ) from last_error
        text = str(response.get("response", "") or "")
        done = response.get("done") is True
        done_reason = str(response.get("done_reason", "") or "")
        if not done or done_reason == "length" or not text.strip():
            state = done_reason or ("empty" if done else "incomplete")
            raise PipelineError(f"{stage} Ollama response was {state}")
        input_tokens = response.get("prompt_eval_count", 0)
        output_tokens = response.get("eval_count", 0)
        if type(input_tokens) is not int or type(output_tokens) is not int:
            raise PipelineError("Ollama token usage was invalid")
        created_at = str(response.get("created_at", "") or "")
        response_id = (
            "ollama:"
            + digest(
                [
                    self.config.model,
                    stage,
                    created_at,
                    hashlib.sha256(input_text.encode()).hexdigest(),
                ]
            )[:24]
        )
        return Generation(
            text=text,
            response_id=response_id,
            model=str(response.get("model", self.config.model)),
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )


def _validate_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or set(payload) != ALLOWED_PAYLOAD_KEYS:
        raise ValueError(
            "Runner accepts only schema_version, repeat_id, blocks, and questions"
        )
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
        if not all(
            isinstance(block[key], str) for key in ("block_id", "document_id", "text")
        ):
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
            segments.append(
                {"block": block, "start": start, "end": end, "text": text[start:end]}
            )
    return segments


def synthesis_batches(
    blocks: list[dict[str, Any]], limit: int
) -> list[list[dict[str, Any]]]:
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
        rows.append(
            f"SOURCE {json.dumps(header, ensure_ascii=False)}\n{segment['text']}"
        )
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


def bm25_search(
    query: str, chunks: list[dict[str, Any]], top_k: int
) -> list[dict[str, Any]]:
    tokenized = [tokenize(chunk["text"]) for chunk in chunks]
    query_tokens = tokenize(query)
    document_count = len(chunks)
    average_length = (
        sum(map(len, tokenized)) / document_count if document_count else 0.0
    )
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
                1
                + (document_count - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * len(tokens) / (average_length or 1.0)
            )
            score += inverse * frequency * 2.5 / denominator
        scored.append({**chunk, "score": round(score, 8)})
    scored.sort(key=lambda row: (-row["score"], row["chunk_id"]))
    return scored[: min(top_k, len(scored))]


def _parse_qa(
    text: str, valid_chunk_ids: set[str], contract: str = "concise_v1"
) -> tuple[str, list[str], dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise PipelineError("QA response was not one valid JSON object") from error
    _, _, schema = _qa_contract(contract)
    required = set(schema["required"])
    if not isinstance(value, dict) or set(value) != required:
        raise PipelineError(
            f"QA response must contain only {', '.join(sorted(required))}"
        )
    if contract == "concise_v1":
        if not isinstance(value["answer"], str) or not value["answer"].strip():
            raise PipelineError("QA answer is missing")
        answer = value["answer"].strip()
    else:
        if not all(
            isinstance(value[key], str)
            for key in ("conclusion", "quantitative_explanation")
        ):
            raise PipelineError(
                "Quantitative QA conclusion or explanation must be a string"
            )
        calculations = value["calculations"]
        if not isinstance(calculations, list) or not all(
            isinstance(item, str) for item in calculations
        ):
            raise PipelineError("Quantitative QA calculations must be a string array")
        parts = [
            value["conclusion"].strip(),
            value["quantitative_explanation"].strip(),
            *[item.strip() for item in calculations],
        ]
        # The provider schema requires strings but cannot guarantee nonempty content. Preserve
        # blank required fields in structured_output so the evaluator can score them as missing;
        # aborting here would discard the model response and bias failure accounting.
        answer = "\n".join(part for part in parts if part)
        if not answer:
            answer = "[MODEL_RETURNED_NO_QUANTITATIVE_CONTENT]"
    evidence = value["evidence_chunk_ids"]
    if not isinstance(evidence, list) or not all(
        isinstance(item, str) for item in evidence
    ):
        raise PipelineError("QA evidence_chunk_ids must be a string array")
    if set(evidence) - valid_chunk_ids:
        raise PipelineError("QA cited unavailable chunks")
    return answer, list(dict.fromkeys(evidence)), value


def _usage_total(generations: list[Generation]) -> dict[str, int]:
    return {
        key: sum(generation.usage.get(key, 0) for generation in generations)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }


def _code_provenance() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    files = [root / "research/pipeline_runner.py", root / "research/pilot.py"]
    file_hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
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


def _generator_for(config: RunnerConfig) -> Generator:
    if config.provider == "ollama_generate":
        return OllamaGenerateAdapter(config)
    return OpenAIResponsesAdapter(config)


def run_pipeline(
    payload: dict[str, Any],
    config: RunnerConfig,
    generator: Generator | None = None,
    *,
    forced_evidence_block_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    config.validate()
    _validate_payload(payload)
    available_block_ids = {block["block_id"] for block in payload["blocks"]}
    if forced_evidence_block_ids is not None:
        if not forced_evidence_block_ids:
            raise ValueError("Forced evidence must name at least one source block")
        unknown = set(forced_evidence_block_ids) - available_block_ids
        if unknown:
            raise ValueError(
                f"Forced evidence contains unknown block IDs: {sorted(unknown)}"
            )
    if not config.model:
        raise ValueError("Set model in config or RESEARCH_LLM_MODEL")
    batches = synthesis_batches(payload["blocks"], config.synthesis_batch_chars)
    model_synthesis_call_count = len(batches) if config.synthesis_mode == "model" else 0
    expected_calls = model_synthesis_call_count + len(payload["questions"])
    if expected_calls > config.max_calls_per_pipeline:
        raise PipelineError(
            f"Expected {expected_calls} calls exceeds max_calls_per_pipeline="
            f"{config.max_calls_per_pipeline}"
        )
    if generator is None:
        generator = _generator_for(config)
    qa_prompt_version, qa_instructions, _ = _qa_contract(config.qa_output_contract)
    execution_id = str(uuid4())
    started_at = datetime.now(UTC).isoformat()
    trace: list[dict[str, Any]] = []
    generations: list[Generation] = []
    synthesized: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []

    if config.synthesis_mode == "model":
        for index, batch in enumerate(batches):
            input_text = _synthesis_input(batch)
            generation = generator.generate(
                stage="synthesis",
                instructions=SYNTHESIS_INSTRUCTIONS,
                input_text=input_text,
                max_output_tokens=config.synthesis_max_output_tokens,
            )
            generations.append(generation)
            source_ids = list(
                dict.fromkeys(item["block"]["block_id"] for item in batch)
            )
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
                    "output_sha256": hashlib.sha256(
                        generation.text.encode()
                    ).hexdigest(),
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
                _chunk_text(
                    generation.text, config.chunk_chars, config.chunk_overlap_chars
                )
            ):
                referenced = [
                    item for item in SOURCE_PATTERN.findall(text) if item in source_ids
                ]
                chunk_sources = list(dict.fromkeys(referenced)) or source_ids
                chunk = {
                    "chunk_id": f"chunk:{execution_id}:{index}:{chunk_index}",
                    "parent_synthesis_id": synthesis_id,
                    "source_block_ids": chunk_sources,
                    "lineage_mode": (
                        "explicit_source_markers"
                        if referenced
                        else "synthesis_batch_fallback"
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
    else:
        for index, block in enumerate(payload["blocks"]):
            source_id = block["block_id"]
            text = block["text"]
            synthesis_id = f"passthrough:{execution_id}:{index}"
            synthesized.append(
                {
                    "synthesis_id": synthesis_id,
                    "text": text,
                    "source_block_ids": [source_id],
                }
            )
            trace.append(
                {
                    "stage": "passthrough",
                    "input_ids": [source_id],
                    "input_text": text,
                    "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "output_id": synthesis_id,
                    "output_text": text,
                    "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "source_spans": [
                        {"block_id": source_id, "start": 0, "end": len(text)}
                    ],
                    "transform_version": PASSTHROUGH_VERSION,
                }
            )
            output_chunks = []
            for chunk_index, (start, end, chunk_text) in enumerate(
                _chunk_text(text, config.chunk_chars, config.chunk_overlap_chars)
            ):
                chunk = {
                    "chunk_id": f"chunk:{execution_id}:{index}:{chunk_index}",
                    "parent_synthesis_id": synthesis_id,
                    "source_block_ids": [source_id],
                    "lineage_mode": "deterministic_passthrough",
                    "start": start,
                    "end": end,
                    "text": chunk_text,
                }
                chunks.append(chunk)
                output_chunks.append(chunk)
            trace.append(
                {
                    "stage": "chunking",
                    "input_ids": [synthesis_id],
                    "input_text": text,
                    "output": output_chunks,
                }
            )
    if not chunks:
        raise PipelineError("Pipeline produced no searchable chunks")

    answers = []
    for question in payload["questions"]:
        if forced_evidence_block_ids is None:
            retrieved = bm25_search(
                question["question"], chunks, config.retrieval_top_k
            )
            retrieval_mode = "bm25_top_k"
        else:
            forced = set(forced_evidence_block_ids)
            retrieved = [
                {**chunk, "score": None}
                for chunk in chunks
                if forced & set(chunk["source_block_ids"])
            ]
            retrieval_mode = "forced_source_blocks_evaluation_diagnostic"
            if not retrieved:
                raise PipelineError("Forced evidence blocks produced no chunks")
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
                "retrieval_mode": retrieval_mode,
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
            instructions=qa_instructions,
            input_text=qa_input,
            max_output_tokens=config.qa_max_output_tokens,
        )
        generations.append(generation)
        answer, evidence_chunk_ids, structured_output = _parse_qa(
            generation.text,
            {row["chunk_id"] for row in retrieved},
            config.qa_output_contract,
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
                "qa_output_contract": config.qa_output_contract,
                "structured_output": structured_output,
                "qa_contract_violations": (
                    [
                        field
                        for field in ("conclusion", "quantitative_explanation")
                        if not structured_output.get(field, "").strip()
                    ]
                    + (
                        ["calculations"]
                        if not any(
                            item.strip()
                            for item in structured_output.get("calculations", [])
                        )
                        else []
                    )
                )
                if config.qa_output_contract == "quantitative_v2"
                else [],
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
                    "qa_output_contract": config.qa_output_contract,
                    "structured_output": structured_output,
                    "qa_contract_violations": answers[-1]["qa_contract_violations"],
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
        "execution_mode": getattr(
            generator, "execution_mode", "test_or_custom_generator"
        ),
        "pipeline_execution_id": execution_id,
        "provider": config.provider,
        "requested_model": config.model,
        "response_models": sorted({generation.model for generation in generations}),
        "prompt_versions": {
            "synthesis": (
                SYNTHESIS_PROMPT_VERSION
                if config.synthesis_mode == "model"
                else PASSTHROUGH_VERSION
            ),
            "qa": qa_prompt_version,
        },
        "prompt_sha256": {
            "synthesis": (
                hashlib.sha256(SYNTHESIS_INSTRUCTIONS.encode()).hexdigest()
                if config.synthesis_mode == "model"
                else None
            ),
            "qa": hashlib.sha256(qa_instructions.encode()).hexdigest(),
        },
        "applied_generation_settings": {
            "store": False,
            "synthesis_mode": config.synthesis_mode,
            "reasoning_effort": config.reasoning_effort,
            "verbosity": config.verbosity,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "qa_response_format": "strict_json_schema",
            "qa_output_contract": config.qa_output_contract,
            "synthesis_max_output_tokens": config.synthesis_max_output_tokens,
            "qa_max_output_tokens": config.qa_max_output_tokens,
        },
        "sdk": getattr(generator, "sdk", "custom-generator"),
        "sdk_version": getattr(generator, "sdk_version", None),
        "provider_runtime": getattr(generator, "provider_runtime", {}),
        "runner_config": config.public_dict(),
        "input_sha256": digest(payload),
        **code_provenance,
        "call_count": len(generations),
        "model_synthesis_call_count": model_synthesis_call_count,
        "usage": _usage_total(generations),
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "source_kinds": sorted(
            {block.get("source_kind", "unspecified") for block in payload["blocks"]}
        ),
        "retrieval_mode": (
            "bm25_top_k"
            if forced_evidence_block_ids is None
            else "forced_source_blocks_evaluation_diagnostic"
        ),
        "forced_evidence_block_ids": list(forced_evidence_block_ids or ()),
        "synthesis_count": len(synthesized),
        "chunk_count": len(chunks),
    }
    return {"answers": answers, "metadata": metadata, "trace": trace}


def preflight(
    case: dict[str, Any], config: RunnerConfig, repeats: int
) -> dict[str, Any]:
    config.validate()
    if repeats < 1:
        raise ValueError("repeats must be positive")
    rows = []
    total = 0
    total_max_output_tokens = 0
    for repeat in range(repeats):
        for condition, repairs in CONDITIONS.items():
            payload = runner_payload(case, repairs, repeat)
            batches = len(
                synthesis_batches(payload["blocks"], config.synthesis_batch_chars)
            )
            synthesis_calls = batches if config.synthesis_mode == "model" else 0
            questions = len(payload["questions"])
            calls = synthesis_calls + questions
            max_output_tokens = (
                synthesis_calls * config.synthesis_max_output_tokens
                + questions * config.qa_max_output_tokens
            )
            rows.append(
                {
                    "repeat_id": repeat,
                    "condition": condition,
                    "synthesis_mode": config.synthesis_mode,
                    "synthesis_calls": synthesis_calls,
                    "qa_calls": questions,
                    "total_calls": calls,
                    "max_output_tokens": max_output_tokens,
                    "input_characters": sum(
                        len(block["text"]) for block in payload["blocks"]
                    ),
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
    run.add_argument("--force-evidence-block-id", action="append", default=[])
    estimate = subparsers.add_parser("preflight")
    estimate.add_argument("--case", type=Path, required=True)
    estimate.add_argument("--config", type=Path)
    estimate.add_argument("--repeats", type=int, default=1)
    estimate.add_argument("--max-total-calls", type=int)
    args = parser.parse_args()
    config = RunnerConfig.load(args.config)
    if args.action == "run":
        response = run_pipeline(
            _read_stdin_payload(),
            config,
            forced_evidence_block_ids=(
                tuple(args.force_evidence_block_id)
                if args.force_evidence_block_id
                else None
            ),
        )
        print(json.dumps(response, ensure_ascii=False))
        return
    case = json.loads(args.case.read_text())
    report = preflight(case, config, args.repeats)
    allowed = args.max_total_calls
    report["max_total_calls"] = allowed
    report["within_call_budget"] = (
        allowed is None or report["estimated_model_calls"] <= allowed
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["within_call_budget"]:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, PipelineError) as error:
        print(f"Pipeline runner stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
