"""Grounded arithmetic-tool QA over only the current parser evidence state."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, Protocol

from research.allocation import NUMERIC_PATTERN
from research.pipeline_runner import Generation, PipelineError

CALCULATOR_PIPELINE_VERSION = "grounded-calculator-qa-v1"
CALCULATOR_PLAN_PROMPT_VERSION = "grounded-calculation-plan-json-v1"
CALCULATOR_ANSWER_PROMPT_VERSION = "grounded-calculation-answer-json-v1"

METRIC_CATALOG = {
    "quick_ratio_liquid_components_v1": (
        "Quick ratio is eligible liquid current-asset components divided by current liabilities. "
        "Inventory and prepaid assets are normally excluded; selected components and periods must "
        "be explicit. A value above 1 is a conventional heuristic, not a filing fact."
    ),
    "quick_ratio_current_assets_less_exclusions_v1": (
        "When total current assets and all excluded non-quick components are available, quick ratio "
        "may be computed as (current assets minus inventory and other explicitly excluded current "
        "assets) divided by current liabilities."
    ),
    "gross_margin_v1": "Gross margin is gross profit divided by revenue or net sales, multiplied by 100.",
    "relative_change_v1": (
        "Relative percent change is (new value minus old value) divided by old value, multiplied by 100."
    ),
    "signed_amount_comparison_v1": (
        "Compare amounts with their reported signs preserved; a positive value is greater than a "
        "negative value unless the question explicitly asks for absolute magnitude."
    ),
    "direct_source_fact_v1": "A direct fact is copied from a cited current-evidence source without arithmetic.",
}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "metric_name": {"type": "string"},
        "metric_definition_id": {"type": "string", "enum": sorted(METRIC_CATALOG)},
        "metric_definition": {"type": "string"},
        "inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "alias": {"type": "string"},
                    "source_id": {"type": "string"},
                    "role": {"type": "string"},
                    "row_label": {"type": "string"},
                    "period": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": [
                    "alias",
                    "source_id",
                    "role",
                    "row_label",
                    "period",
                    "unit",
                ],
                "additionalProperties": False,
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": [
                            "identity",
                            "add",
                            "subtract",
                            "multiply",
                            "divide",
                            "percent",
                            "percent_change",
                            "absolute",
                            "max",
                            "min",
                            "greater_than_one",
                            "less_than_one",
                        ],
                    },
                    "operands": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["step_id", "operation", "operands"],
                "additionalProperties": False,
            },
        },
        "outputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "ref": {"type": "string"}},
                "required": ["name", "ref"],
                "additionalProperties": False,
            },
        },
        "answer_focus": {"type": "string"},
    },
    "required": [
        "metric_name",
        "metric_definition_id",
        "metric_definition",
        "inputs",
        "steps",
        "outputs",
        "answer_focus",
    ],
    "additionalProperties": False,
}

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "conclusion": {"type": "string"},
        "quantitative_explanation": {"type": "string"},
        "calculations": {"type": "array", "items": {"type": "string"}},
        "evidence_source_ids": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "used_output_names": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
    },
    "required": [
        "conclusion",
        "quantitative_explanation",
        "calculations",
        "evidence_source_ids",
        "used_output_names",
    ],
    "additionalProperties": False,
}

PLAN_INSTRUCTIONS = """Select a metric and a calculation plan using only the current evidence
sources in the input. Use source_id values exactly as shown. Do not use a question ID, document
name, memorized filing value, reference answer, or unstated value. Choose the row, period, sign,
unit, and denominator explicitly. Use only the listed generic metric definitions and operations.
Return exactly one JSON object matching the schema."""

ANSWER_INSTRUCTIONS = """Answer using only the validated calculation record and selected current
evidence sources in the input. Do not redo arithmetic mentally or substitute another value. State
a direct conclusion, the material values with rows/periods/units, the program calculation, and
the supporting evidence_source_ids. If metric or source selection was wrong or insufficient, say
so instead of inventing a correction. Return exactly one JSON object matching the schema."""


class StructuredGenerator(Protocol):
    def generate_structured(
        self,
        *,
        stage: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
        response_schema: dict[str, Any],
    ) -> Generation: ...


def _decimal(raw: str) -> Decimal:
    value = raw.strip().replace("−", "-")
    percent = value.endswith("%")
    value = value.removesuffix("%").replace("$", "").strip()
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()").replace(",", "")
    number = Decimal(value)
    if negative:
        number = -number
    return number / 100 if percent else number


def _page_unit_context(
    blocks: list[dict[str, Any]], page_number: int
) -> tuple[str, str | None]:
    for block in blocks:
        if block.get("page_number") != page_number:
            continue
        match = re.search(r"\$\s+in\s+millions", block.get("text", ""), re.IGNORECASE)
        if match:
            return "USD millions", block["block_id"]
    return "", None


def _cell_labels(cells: list[dict[str, Any]], cell: dict[str, Any]) -> tuple[str, str]:
    row = cell.get("row")
    column = cell.get("column")
    row_candidates = [
        other
        for other in cells
        if other.get("row") == row
        and isinstance(other.get("text"), str)
        and other.get("text", "").strip()
        and (
            other.get("attributes", {}).get("row_header") is True
            or other.get("column") == 0
        )
    ]
    column_candidates = [
        other
        for other in cells
        if other.get("column") == column
        and isinstance(other.get("text"), str)
        and other.get("text", "").strip()
        and other.get("attributes", {}).get("column_header") is True
    ]
    row_label = row_candidates[0]["text"] if row_candidates else ""
    column_label = column_candidates[-1]["text"] if column_candidates else ""
    return row_label, column_label


def extract_numeric_sources(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enumerate current-state values; no reference answers or repairs are accepted."""
    sources: list[dict[str, Any]] = []
    for block in blocks:
        block_id = block["block_id"]
        page_number = block["page_number"]
        cells = block.get("cells")
        if isinstance(cells, list) and cells:
            unit, unit_source = _page_unit_context(blocks, page_number)
            for cell_index, cell in enumerate(cells):
                if not isinstance(cell, dict) or not isinstance(cell.get("text"), str):
                    continue
                row_label, column_label = _cell_labels(cells, cell)
                for match_index, match in enumerate(
                    NUMERIC_PATTERN.finditer(cell["text"])
                ):
                    try:
                        value = _decimal(match.group(0))
                    except InvalidOperation:
                        continue
                    cell_id = cell.get("id") or f"{block_id}:cell-{cell_index}"
                    sources.append(
                        {
                            "source_id": f"{cell_id}:number-{match_index}",
                            "block_id": block_id,
                            "page_number": page_number,
                            "table_id": block_id,
                            "cell_id": cell_id,
                            "row": cell.get("row"),
                            "column": cell.get("column"),
                            "row_label": row_label,
                            "column_label": column_label,
                            "unit": unit,
                            "unit_source_id": unit_source,
                            "observed_text": match.group(0),
                            "value": str(value),
                            "context": cell["text"],
                            "bbox": cell.get("bbox"),
                            "coordinate_source": cell.get("attributes", {}).get(
                                "coordinate_source"
                            ),
                            "association_method": "derived_from_parser_table_cells",
                        }
                    )
            continue
        text = block.get("text", "")
        for match_index, match in enumerate(NUMERIC_PATTERN.finditer(text)):
            try:
                value = _decimal(match.group(0))
            except InvalidOperation:
                continue
            start, end = match.span()
            sources.append(
                {
                    "source_id": f"{block_id}:number-{match_index}:{start}-{end}",
                    "block_id": block_id,
                    "page_number": page_number,
                    "table_id": None,
                    "cell_id": None,
                    "row": None,
                    "column": None,
                    "row_label": "",
                    "column_label": "",
                    "unit": "",
                    "unit_source_id": None,
                    "observed_text": match.group(0),
                    "value": str(value),
                    "context": text[max(0, start - 80) : min(len(text), end + 80)],
                    "bbox": None,
                    "coordinate_source": None,
                    "association_method": "flat_text_numeric_span",
                }
            )
    ids = [row["source_id"] for row in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Numeric source IDs are not unique")
    return sources


def _json_object(text: str, expected: set[str]) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise PipelineError(
            "Structured calculator response was not valid JSON"
        ) from error
    if not isinstance(value, dict) or set(value) != expected:
        raise PipelineError(
            "Structured calculator response keys did not match the contract"
        )
    return value


@dataclass(frozen=True)
class _Node:
    value: Decimal | bool
    selected_ref: str | None = None


def _execute(operation: str, operands: list[tuple[str, _Node]]) -> _Node:
    values = [node.value for _, node in operands]
    if operation == "identity" and len(values) == 1:
        return _Node(values[0], operands[0][0])
    if not all(isinstance(value, Decimal) for value in values):
        raise PipelineError(
            "Boolean calculation output cannot be used as a numeric operand"
        )
    decimals = [value for value in values if isinstance(value, Decimal)]
    if operation == "add" and len(decimals) >= 2:
        return _Node(sum(decimals, Decimal(0)))
    if operation == "subtract" and len(decimals) == 2:
        return _Node(decimals[0] - decimals[1])
    if operation == "multiply" and len(decimals) >= 2:
        result = Decimal(1)
        for value in decimals:
            result *= value
        return _Node(result)
    if operation == "divide" and len(decimals) == 2:
        return _Node(decimals[0] / decimals[1])
    if operation == "percent" and len(decimals) == 1:
        return _Node(decimals[0] * 100)
    if operation == "percent_change" and len(decimals) == 2:
        return _Node((decimals[0] - decimals[1]) / decimals[1] * 100)
    if operation == "absolute" and len(decimals) == 1:
        return _Node(abs(decimals[0]))
    if operation in {"max", "min"} and len(decimals) >= 2:
        chosen = max(decimals) if operation == "max" else min(decimals)
        selected = operands[decimals.index(chosen)][0]
        return _Node(chosen, selected)
    if operation == "greater_than_one" and len(decimals) == 1:
        return _Node(decimals[0] > 1, operands[0][0])
    if operation == "less_than_one" and len(decimals) == 1:
        return _Node(decimals[0] < 1, operands[0][0])
    raise PipelineError(f"Invalid arity for calculator operation {operation}")


def execute_plan(plan: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    if plan.get("metric_definition_id") not in METRIC_CATALOG:
        raise PipelineError("Unknown metric definition")
    source_map = {row["source_id"]: row for row in sources}
    aliases: dict[str, _Node] = {}
    selected_sources: list[dict[str, Any]] = []
    for item in plan.get("inputs", []):
        alias = item.get("alias")
        source_id = item.get("source_id")
        if not isinstance(alias, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*", alias
        ):
            raise PipelineError("Calculator input alias is invalid")
        if alias in aliases or source_id not in source_map:
            raise PipelineError("Calculator input source is unknown or duplicated")
        source = source_map[source_id]
        aliases[alias] = _Node(Decimal(source["value"]), source_id)
        selected_sources.append({**source, "plan_interpretation": item})
    if not aliases:
        raise PipelineError("Calculator plan selected no current-evidence values")
    nodes = dict(aliases)
    steps = []
    for step in plan.get("steps", []):
        step_id = step.get("step_id")
        refs = step.get("operands")
        operation = step.get("operation")
        if (
            not isinstance(step_id, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", step_id)
            or step_id in nodes
            or not isinstance(refs, list)
            or not all(isinstance(ref, str) and ref in nodes for ref in refs)
            or not isinstance(operation, str)
        ):
            raise PipelineError(
                "Calculator step references are invalid or non-topological"
            )
        try:
            result = _execute(operation, [(ref, nodes[ref]) for ref in refs])
        except (DivisionByZero, InvalidOperation, ZeroDivisionError) as error:
            raise PipelineError("Calculator arithmetic failed") from error
        nodes[step_id] = result
        steps.append(
            {
                "step_id": step_id,
                "operation": operation,
                "operand_refs": refs,
                "operands": [str(nodes[ref].value) for ref in refs],
                "result": str(result.value),
                "selected_ref": result.selected_ref,
            }
        )
    outputs = []
    seen_output_names: set[str] = set()
    for output in plan.get("outputs", []):
        name = output.get("name")
        ref = output.get("ref")
        if (
            not isinstance(name, str)
            or not name
            or name in seen_output_names
            or ref not in nodes
        ):
            raise PipelineError("Calculator output reference is invalid")
        seen_output_names.add(name)
        node = nodes[ref]
        outputs.append(
            {
                "name": name,
                "ref": ref,
                "value": str(node.value),
                "selected_ref": node.selected_ref,
            }
        )
    if not outputs:
        raise PipelineError("Calculator plan produced no named outputs")
    return {
        "pipeline_version": CALCULATOR_PIPELINE_VERSION,
        "metric_name": plan["metric_name"],
        "metric_definition_id": plan["metric_definition_id"],
        "catalog_definition": METRIC_CATALOG[plan["metric_definition_id"]],
        "model_stated_definition": plan["metric_definition"],
        "selected_sources": selected_sources,
        "steps": steps,
        "outputs": outputs,
    }


def run_calculator_qa(
    *,
    question: dict[str, str],
    blocks: list[dict[str, Any]],
    generator: StructuredGenerator,
    planner_max_output_tokens: int = 1_000,
    answer_max_output_tokens: int = 700,
) -> dict[str, Any]:
    sources = extract_numeric_sources(blocks)
    if not sources:
        raise PipelineError("Current evidence contained no numeric sources")
    plan_input = json.dumps(
        {
            "question": question["question"],
            "metric_catalog": METRIC_CATALOG,
            "current_evidence_sources": sources,
        },
        ensure_ascii=False,
    )
    plan_generation = generator.generate_structured(
        stage="calculator_plan",
        instructions=PLAN_INSTRUCTIONS,
        input_text=plan_input,
        max_output_tokens=planner_max_output_tokens,
        response_schema=PLAN_SCHEMA,
    )
    plan = _json_object(plan_generation.text, set(PLAN_SCHEMA["required"]))
    calculation = execute_plan(plan, sources)
    valid_source_ids = [row["source_id"] for row in calculation["selected_sources"]]
    valid_output_names = [row["name"] for row in calculation["outputs"]]
    answer_schema = json.loads(json.dumps(ANSWER_SCHEMA))
    answer_schema["properties"]["evidence_source_ids"]["items"]["enum"] = (
        valid_source_ids
    )
    answer_schema["properties"]["used_output_names"]["items"]["enum"] = (
        valid_output_names
    )
    answer_input = json.dumps(
        {
            "question": question["question"],
            "validated_plan": plan,
            "program_calculation": calculation,
        },
        ensure_ascii=False,
    )
    answer_generation = generator.generate_structured(
        stage="calculator_answer",
        instructions=ANSWER_INSTRUCTIONS,
        input_text=answer_input,
        max_output_tokens=answer_max_output_tokens,
        response_schema=answer_schema,
    )
    answer = _json_object(answer_generation.text, set(ANSWER_SCHEMA["required"]))
    evidence_ids = answer["evidence_source_ids"]
    output_names = answer["used_output_names"]
    if (
        not isinstance(evidence_ids, list)
        or set(evidence_ids) - set(valid_source_ids)
        or not isinstance(output_names, list)
        or set(output_names) - set(valid_output_names)
    ):
        raise PipelineError("Calculator answer cited unavailable sources or outputs")
    return {
        "question_id": question["question_id"],
        "pipeline_version": CALCULATOR_PIPELINE_VERSION,
        "numeric_sources": sources,
        "plan": plan,
        "calculation": calculation,
        "answer": answer,
        "answer_text": "\n".join(
            [
                answer["conclusion"],
                answer["quantitative_explanation"],
                *answer["calculations"],
            ]
        ).strip(),
        "prompt_versions": {
            "planner": CALCULATOR_PLAN_PROMPT_VERSION,
            "answerer": CALCULATOR_ANSWER_PROMPT_VERSION,
        },
        "call_usage": {
            "planner": plan_generation.usage,
            "answerer": answer_generation.usage,
        },
        "dependency_edges": [
            *[
                {
                    "from": row["source_id"],
                    "to": row["plan_interpretation"]["alias"],
                    "kind": "selected_current_value",
                }
                for row in calculation["selected_sources"]
            ],
            *[
                {"from": ref, "to": step["step_id"], "kind": "calculator_operand"}
                for step in calculation["steps"]
                for ref in step["operand_refs"]
            ],
            *[
                {
                    "from": output["ref"],
                    "to": f"answer:{question['question_id']}",
                    "kind": "reported_calculator_output",
                }
                for output in calculation["outputs"]
                if output["name"] in output_names
            ],
        ],
    }
