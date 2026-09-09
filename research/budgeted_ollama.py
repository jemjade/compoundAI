"""Append-only local Ollama call ledger with a hard cross-pipeline budget."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research.pilot import write_json
from research.pipeline_runner import (
    Generation,
    OllamaGenerateAdapter,
    PipelineError,
    RunnerConfig,
)


class BudgetedOllamaGenerator:
    execution_mode = "live_local_model_budgeted"
    sdk = "ollama-native-http"

    def __init__(
        self,
        config: RunnerConfig,
        ledger_dir: Path,
        hard_limit: int,
        *,
        initial_call_count: int = 0,
    ) -> None:
        if config.provider != "ollama_generate" or config.max_retries != 0:
            raise ValueError(
                "The research budget ledger requires local Ollama with zero retries"
            )
        if hard_limit < 1 or not 0 <= initial_call_count < hard_limit:
            raise ValueError("hard_limit and initial_call_count leave no call budget")
        self.config = config
        self.ledger_dir = ledger_dir
        self.hard_limit = hard_limit
        self.call_count = initial_call_count
        self.initial_call_count = initial_call_count
        self.adapter = OllamaGenerateAdapter(config)
        self.provider_runtime = self.adapter.provider_runtime
        self.sdk_version = self.adapter.sdk_version

    def _call(
        self,
        *,
        stage: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> Generation:
        if self.call_count >= self.hard_limit:
            raise PipelineError(f"Global live call limit {self.hard_limit} exhausted")
        self.call_count += 1
        path = self.ledger_dir / f"call-{self.call_count:03d}.json"
        started_at = datetime.now(UTC).isoformat()
        base = {
            "schema_version": 1,
            "call_index": self.call_count,
            "phase_initial_call_count": getattr(self, "initial_call_count", 0),
            "hard_limit": self.hard_limit,
            "stage": stage,
            "instructions": instructions,
            "input_text": input_text,
            "max_output_tokens": max_output_tokens,
            "response_schema": response_schema,
            "started_at": started_at,
            "status": "started",
        }
        write_json(path, base)
        try:
            result = self.adapter.generate_with_schema(
                stage=stage,
                instructions=instructions,
                input_text=input_text,
                max_output_tokens=max_output_tokens,
                response_schema=response_schema,
            )
        except Exception as error:
            raw_provider_response = getattr(self.adapter, "last_raw_response", None)
            write_json(
                path,
                {
                    **base,
                    "status": "failed",
                    "failure_type": type(error).__name__,
                    "failure_message": str(error),
                    "raw_provider_response": raw_provider_response,
                    "finished_at": datetime.now(UTC).isoformat(),
                },
            )
            raise
        write_json(
            path,
            {
                **base,
                "status": "completed",
                "raw_output": result.text,
                "response_id": result.response_id,
                "response_model": result.model,
                "usage": result.usage,
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
        return result

    def generate(
        self,
        *,
        stage: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> Generation:
        from research.pipeline_runner import _qa_response_schema

        schema = (
            _qa_response_schema(input_text, self.config.qa_output_contract)
            if stage == "qa"
            else None
        )
        return self._call(
            stage=stage,
            instructions=instructions,
            input_text=input_text,
            max_output_tokens=max_output_tokens,
            response_schema=schema,
        )

    def generate_structured(
        self,
        *,
        stage: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
        response_schema: dict[str, Any],
    ) -> Generation:
        return self._call(
            stage=stage,
            instructions=instructions,
            input_text=input_text,
            max_output_tokens=max_output_tokens,
            response_schema=response_schema,
        )
