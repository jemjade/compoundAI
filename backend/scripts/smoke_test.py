"""실행 중인 ParseLab API에서 Phase 1~4 전체 흐름을 검증한다."""

import argparse
import time
from uuid import uuid4

import httpx


def check(response: httpx.Response) -> dict:
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    args = parser.parse_args()
    email = f"smoke-{uuid4().hex[:10]}@example.com"
    password = "smoke-test-password"

    with httpx.Client(base_url=args.base_url, timeout=15) as client:
        signup = check(
            client.post(
                "/auth/signup",
                json={"email": email, "password": password, "name": "Smoke Admin"},
            )
        )
        if signup["role"] != "ADMIN":
            raise RuntimeError(
                "Smoke test requires an empty database so its account becomes ADMIN."
            )
        login = check(client.post("/auth/login", json={"email": email, "password": password}))
        client.headers["Authorization"] = f"Bearer {login['access_token']}"

        document = check(
            client.post(
                "/documents",
                files={
                    "file": (
                        "sample.txt",
                        (
                            "ParseLab smoke test@example.com\n\n"
                            "연락처 010-1234-5678 문서를 세 파서로 비교합니다."
                        ),
                        "text/plain",
                    )
                },
            )
        )
        parsers = check(client.get("/parsers"))
        if len(parsers) < 2:
            raise RuntimeError("Expected the first signup to seed two mock parsers.")
        command_parser = check(
            client.post(
                "/parsers",
                json={
                    "name": "UV Command",
                    "slug": f"uv-command-{uuid4().hex[:6]}",
                    "description": "Phase 2 command smoke test",
                    "provider": "ParseLab",
                    "model_name": "uv",
                    "model_version": "local",
                    "execution_type": "COMMAND",
                    "adapter_key": "generic_command",
                    "base_url": None,
                    "command_template": ["uv", "--version"],
                    "default_config": {},
                    "config_schema": {
                        "type": "object",
                        "additionalProperties": False,
                    },
                    "capabilities": ["TEXT"],
                    "supported_formats": ["txt"],
                    "timeout_seconds": 10,
                },
            )
        )
        command_parser = check(
            client.patch(
                f"/parsers/{command_parser['id']}",
                json={"description": "Phase 2 command adapter verified"},
            )
        )
        health = check(client.post(f"/parsers/{command_parser['id']}/health-check"))
        if not health["healthy"]:
            raise RuntimeError("Generic command parser health check failed.")
        preset = check(
            client.post(
                f"/parsers/{command_parser['id']}/presets",
                json={"name": "Default smoke", "config": {}},
            )
        )
        presets = check(client.get(f"/parsers/{command_parser['id']}/presets"))
        if [item["id"] for item in presets] != [preset["id"]]:
            raise RuntimeError("Parser preset was not persisted.")

        created = check(
            client.post(
                "/experiments",
                json={
                    "name": "Container smoke test",
                    "document_id": document["id"],
                    "run_deidentification": True,
                    "parser_runs": [
                        {
                            "parser_connector_id": item["id"],
                            "parser_preset_id": None,
                            "config_override": {},
                        }
                        for item in [*parsers[:2], command_parser]
                    ],
                },
            )
        )
        for _ in range(50):
            detail = check(client.get(f"/experiments/{created['experiment_id']}"))
            if detail["status"] in {
                "COMPLETED",
                "PARTIALLY_COMPLETED",
                "FAILED",
            }:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Experiment did not reach a terminal state.")

        comparison = check(client.get(f"/experiments/{created['experiment_id']}/comparison"))
        if detail["status"] != "COMPLETED":
            raise RuntimeError(f"Experiment ended with {detail['status']}.")
        if len(comparison["runs"]) != 3:
            raise RuntimeError("Expected three comparison results.")
        if any(not run["text"] for run in comparison["runs"]):
            raise RuntimeError("A parser returned empty text.")
        if comparison["runs"][0]["text"] == comparison["runs"][1]["text"]:
            raise RuntimeError("Mock parsers should produce distinct comparison text.")
        if any(run["deidentification_status"] != "SUCCEEDED" for run in comparison["runs"]):
            raise RuntimeError("A deidentification run did not succeed.")
        if any(run["deidentified"] is None for run in comparison["runs"]):
            raise RuntimeError("A deidentified comparison result is missing.")
        if any(run["canonical"] is None for run in comparison["runs"]):
            raise RuntimeError("A Canonical JSON comparison result is missing.")
        text_diff = check(
            client.get(
                f"/experiments/{created['experiment_id']}/text-diff",
                params={
                    "base_run_id": comparison["runs"][0]["run_id"],
                    "target_run_id": comparison["runs"][1]["run_id"],
                    "normalize_whitespace": "true",
                },
            )
        )
        if text_diff["similarity_ratio"] >= 1:
            raise RuntimeError("Expected distinct mock parser text diff results.")
        check(
            client.put(
                f"/runs/{comparison['runs'][0]['run_id']}/evaluation",
                json={
                    "text_score": 4,
                    "table_score": 3,
                    "reading_order_score": 4,
                    "deidentification_score": 5,
                    "is_preferred": True,
                    "notes": "First smoke preference",
                },
            )
        )
        check(
            client.put(
                f"/runs/{comparison['runs'][1]['run_id']}/evaluation",
                json={
                    "text_score": 5,
                    "table_score": 4,
                    "reading_order_score": 5,
                    "deidentification_score": 5,
                    "is_preferred": True,
                    "notes": "Final smoke preference",
                },
            )
        )
        evaluated_comparison = check(
            client.get(f"/experiments/{created['experiment_id']}/comparison")
        )
        preferred_runs = [
            run
            for run in evaluated_comparison["runs"]
            if run["evaluation"] and run["evaluation"]["is_preferred"]
        ]
        if [run["run_id"] for run in preferred_runs] != [comparison["runs"][1]["run_id"]]:
            raise RuntimeError("Exactly the latest preferred run should remain selected.")
        csv_export = client.get(f"/experiments/{created['experiment_id']}/export.csv")
        csv_export.raise_for_status()
        if "run_id,parser_name" not in csv_export.text:
            raise RuntimeError("Comparison CSV header is missing.")
        artifact = client.get(f"/runs/{comparison['runs'][0]['run_id']}/deidentified")
        artifact.raise_for_status()
        if "[EMAIL]" not in artifact.text or "[PHONE]" not in artifact.text:
            raise RuntimeError("Mock Fasoo did not mask expected entities.")

        print(
            "Smoke test passed:",
            created["experiment_id"],
            (f"({len(comparison['runs'])} runs: PARSE + DEIDENTIFY + DIFF + EVALUATION + CSV)"),
        )


if __name__ == "__main__":
    main()
