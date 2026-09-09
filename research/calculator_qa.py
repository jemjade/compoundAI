"""Grounded arithmetic-tool QA over only the current parser evidence state."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, Protocol

from research.allocation import NUMERIC_PATTERN
from research.pipeline_runner import Generation, PipelineError

CALCULATOR_PIPELINE_VERSION = "grounded-calculator-qa-v1"
CALCULATOR_PLAN_PROMPT_VERSION = "grounded-calculation-plan-json-v1"
CALCULATOR_ANSWER_PROMPT_VERSION = "grounded-calculation-answer-json-v1"
SHORT_CALCULATOR_PIPELINE_VERSION = "grounded-calculator-qa-v1_5"
SHORT_PLAN_PROMPT_VERSION = "grounded-calculation-short-plan-json-v1_5"
SHORT_ANSWER_PROMPT_VERSION = "grounded-calculation-short-answer-json-v1_5"
SHORT_PLAN_MAX_INPUTS = 8
SHORT_PLAN_MAX_STEPS = 6
SHORT_PLAN_MAX_OPERANDS = 4
SHORT_PLAN_MAX_OUTPUTS = 4
SHORT_PLANNER_MAX_OUTPUT_TOKENS = 400
SHORT_ANSWER_MAX_OUTPUT_TOKENS = 450
PROMPT_TOKEN_ESTIMATE_CHARS_PER_TOKEN = 3
PROMPT_TOKEN_SAFETY_RESERVE = 512

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

SHORT_PLAN_INSTRUCTIONS = """Choose a metric, current evidence values, and a short arithmetic
plan. Use only the supplied metric IDs, source IDs, roles, and operations. Result r0 is step 0,
r1 is step 1, and so on. A step may use selected source IDs or earlier results only. Do not copy
labels, definitions, values, question IDs, document names, or prose into the output. Do not use
memorized facts or unstated values. Return only the JSON object required by the schema."""

SHORT_ANSWER_INSTRUCTIONS = """Answer only from the validated program record. Cite short source
IDs and result IDs exactly as supplied. State the conclusion, the relevant values with period and
unit, and the program arithmetic. Do not redo arithmetic, substitute values, use outside facts,
or invent missing evidence. Return only the JSON object required by the schema."""

SHORT_ROLES = [
    "numerator",
    "denominator",
    "current",
    "prior",
    "comparison_a",
    "comparison_b",
    "direct_value",
    "component",
    "exclusion",
]
SHORT_OPERATIONS = [
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
]


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


class ShortCalculatorError(PipelineError):
    """A fail-closed v1.5 error that preserves stage-level diagnostics."""

    def __init__(self, message: str, trace: dict[str, Any]) -> None:
        super().__init__(message)
        self.trace = trace


def _header_context(cells: list[dict[str, Any]], cell: dict[str, Any]) -> str:
    """Return parser-provided headers covering the value column, in reading order."""
    column = cell.get("column")
    if not isinstance(column, int):
        return ""
    headers = []
    for other in cells:
        start = other.get("column")
        span = other.get("column_span", 1)
        text = other.get("text")
        if (
            other.get("attributes", {}).get("column_header") is True
            and isinstance(start, int)
            and isinstance(span, int)
            and start <= column < start + span
            and isinstance(text, str)
            and text.strip()
        ):
            headers.append((other.get("row", -1), text.strip()))
    return " | ".join(text for _row, text in sorted(headers))


def _period_and_unit(source: dict[str, Any]) -> tuple[str, str]:
    header = source.get("header_context", "")
    period_match = re.search(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},\s+\d{4}|(?:19|20)\d{2}",
        header,
        re.IGNORECASE,
    )
    period = period_match.group(0) if period_match else source.get("column_label", "")
    unit = source.get("unit", "")
    if not unit and re.search(r"in\s+millions", header, re.IGNORECASE):
        unit = "millions"
    if unit == "millions" and "$" in source.get("observed_text", ""):
        unit = "currency millions ($)"
    return str(period or ""), str(unit or "")


def build_short_source_registry(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map every current-state numeric source to a stable short ID without gold filtering."""
    sources = extract_numeric_sources(blocks)
    cells_by_block = {
        block["block_id"]: block.get("cells", [])
        for block in blocks
        if isinstance(block.get("cells"), list)
    }
    registry = []
    for index, source in enumerate(sources):
        full = dict(source)
        cells = cells_by_block.get(source["block_id"], [])
        cell = next(
            (row for row in cells if row.get("id") == source.get("cell_id")), None
        )
        full["header_context"] = (
            _header_context(cells, cell) if isinstance(cell, dict) else ""
        )
        period, unit = _period_and_unit(full)
        registry.append(
            {
                "short_id": f"s{index}",
                "original_source_id": source["source_id"],
                "planner_view": {
                    "id": f"s{index}",
                    "value": source["value"],
                    "row": source.get("row_label", ""),
                    "period": period,
                    "unit": unit,
                    "context": source.get("context", ""),
                },
                "full_source": full,
            }
        )
    return registry


def short_plan_schema(source_ids: list[str]) -> dict[str, Any]:
    result_ids = [f"r{index}" for index in range(SHORT_PLAN_MAX_STEPS)]
    refs = [*source_ids, *result_ids]
    return {
        "type": "object",
        "properties": {
            "metric_id": {"type": "string", "enum": sorted(METRIC_CATALOG)},
            "inputs": {
                "type": "array",
                "minItems": 1,
                "maxItems": SHORT_PLAN_MAX_INPUTS,
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": SHORT_ROLES},
                        "source": {"type": "string", "enum": source_ids},
                    },
                    "required": ["role", "source"],
                    "additionalProperties": False,
                },
            },
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": SHORT_PLAN_MAX_STEPS,
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": SHORT_OPERATIONS},
                        "args": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": SHORT_PLAN_MAX_OPERANDS,
                            "items": {"type": "string", "enum": refs},
                        },
                    },
                    "required": ["op", "args"],
                    "additionalProperties": False,
                },
            },
            "outputs": {
                "type": "array",
                "minItems": 1,
                "maxItems": SHORT_PLAN_MAX_OUTPUTS,
                "uniqueItems": True,
                "items": {"type": "string", "enum": result_ids},
            },
        },
        "required": ["metric_id", "inputs", "steps", "outputs"],
        "additionalProperties": False,
    }


def short_answer_schema(
    selected_source_ids: list[str], output_ids: list[str]
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "conclusion": {"type": "string", "maxLength": 240},
            "explanation": {"type": "string", "maxLength": 700},
            "calculations": {
                "type": "array",
                "maxItems": SHORT_PLAN_MAX_STEPS,
                "items": {"type": "string", "maxLength": 180},
            },
            "sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": SHORT_PLAN_MAX_INPUTS,
                "uniqueItems": True,
                "items": {"type": "string", "enum": selected_source_ids},
            },
            "results": {
                "type": "array",
                "minItems": 1,
                "maxItems": SHORT_PLAN_MAX_OUTPUTS,
                "uniqueItems": True,
                "items": {"type": "string", "enum": output_ids},
            },
        },
        "required": ["conclusion", "explanation", "calculations", "sources", "results"],
        "additionalProperties": False,
    }


def prepare_short_planner_contract(
    *, question: dict[str, str], blocks: list[dict[str, Any]], num_ctx: int
) -> dict[str, Any]:
    registry = build_short_source_registry(blocks)
    if not registry:
        raise PipelineError("Current evidence contained no numeric sources")
    source_ids = [row["short_id"] for row in registry]
    schema = short_plan_schema(source_ids)
    input_payload = {
        "question": question["question"],
        "metrics": METRIC_CATALOG,
        "sources": [row["planner_view"] for row in registry],
    }
    input_text = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
    estimated_chars = sum(
        len(value)
        for value in (
            SHORT_PLAN_INSTRUCTIONS,
            input_text,
            json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
        )
    )
    estimated_prompt_tokens = math.ceil(
        estimated_chars / PROMPT_TOKEN_ESTIMATE_CHARS_PER_TOKEN
    )
    longest_source = max(source_ids, key=len)
    longest_role = max(SHORT_ROLES, key=len)
    longest_operation = max(SHORT_OPERATIONS, key=len)
    maximum_plan = {
        "metric_id": max(METRIC_CATALOG, key=len),
        "inputs": [
            {"role": longest_role, "source": longest_source}
            for _ in range(SHORT_PLAN_MAX_INPUTS)
        ],
        "steps": [
            {
                "op": longest_operation,
                "args": [f"r{max(0, index - 1)}"] * SHORT_PLAN_MAX_OPERANDS,
            }
            for index in range(SHORT_PLAN_MAX_STEPS)
        ],
        "outputs": [f"r{index}" for index in range(SHORT_PLAN_MAX_OUTPUTS)],
    }
    maximum_plan_chars = len(
        json.dumps(maximum_plan, ensure_ascii=False, separators=(",", ":"))
    )
    maximum_plan_token_estimate = math.ceil(
        maximum_plan_chars / PROMPT_TOKEN_ESTIMATE_CHARS_PER_TOKEN
    )
    estimate = {
        "method": "ceil((instruction+input+schema UTF-8 character count)/3); tokenizer-independent conservative estimate",
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "planner_output_budget_tokens": SHORT_PLANNER_MAX_OUTPUT_TOKENS,
        "safety_reserve_tokens": PROMPT_TOKEN_SAFETY_RESERVE,
        "num_ctx": num_ctx,
        "maximum_plan_json_chars": maximum_plan_chars,
        "maximum_plan_token_estimate": maximum_plan_token_estimate,
        "maximum_plan_fits_output_budget": maximum_plan_token_estimate
        <= SHORT_PLANNER_MAX_OUTPUT_TOKENS,
        "fits": estimated_prompt_tokens
        + SHORT_PLANNER_MAX_OUTPUT_TOKENS
        + PROMPT_TOKEN_SAFETY_RESERVE
        <= num_ctx,
    }
    if not estimate["fits"] or not estimate["maximum_plan_fits_output_budget"]:
        raise PipelineError(
            "Short planner prompt does not leave the frozen output and safety reserve"
        )
    return {
        "registry": registry,
        "schema": schema,
        "input_text": input_text,
        "token_estimate": estimate,
        "candidate_count": len(registry),
        "candidate_reduction": "none; every current-page numeric source is retained",
    }


def execute_short_plan(
    plan: dict[str, Any], registry: list[dict[str, Any]]
) -> dict[str, Any]:
    if set(plan) != {"metric_id", "inputs", "steps", "outputs"}:
        raise PipelineError("Short planner keys did not match the contract")
    if plan.get("metric_id") not in METRIC_CATALOG:
        raise PipelineError("Unknown metric definition")
    inputs = plan.get("inputs")
    steps = plan.get("steps")
    outputs = plan.get("outputs")
    if (
        not isinstance(inputs, list)
        or not 1 <= len(inputs) <= SHORT_PLAN_MAX_INPUTS
        or not isinstance(steps, list)
        or not 1 <= len(steps) <= SHORT_PLAN_MAX_STEPS
        or not isinstance(outputs, list)
        or not 1 <= len(outputs) <= SHORT_PLAN_MAX_OUTPUTS
    ):
        raise PipelineError("Short planner array bounds were violated")
    registry_map = {row["short_id"]: row for row in registry}
    nodes: dict[str, _Node] = {}
    selected = []
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {"role", "source"}:
            raise PipelineError("Short planner input shape is invalid")
        source_id = item["source"]
        if source_id not in registry_map or item["role"] not in SHORT_ROLES:
            raise PipelineError("Short planner selected an unknown source or role")
        if source_id not in nodes:
            source = registry_map[source_id]
            nodes[source_id] = _Node(Decimal(source["full_source"]["value"]), source_id)
        selected.append({**registry_map[source_id], "role": item["role"]})
    executed = []
    for index, step in enumerate(steps):
        result_id = f"r{index}"
        if not isinstance(step, dict) or set(step) != {"op", "args"}:
            raise PipelineError("Short planner step shape is invalid")
        operation = step["op"]
        refs = step["args"]
        if (
            operation not in SHORT_OPERATIONS
            or not isinstance(refs, list)
            or not 1 <= len(refs) <= SHORT_PLAN_MAX_OPERANDS
            or not all(isinstance(ref, str) and ref in nodes for ref in refs)
        ):
            raise PipelineError(
                "Short planner step has an invalid operation, reference, or forward/cyclic reference"
            )
        try:
            result = _execute(operation, [(ref, nodes[ref]) for ref in refs])
        except (DivisionByZero, InvalidOperation, ZeroDivisionError) as error:
            raise PipelineError("Calculator arithmetic failed") from error
        nodes[result_id] = result
        executed.append(
            {
                "result_id": result_id,
                "operation": operation,
                "operand_refs": refs,
                "operands": [str(nodes[ref].value) for ref in refs],
                "result": str(result.value),
                "selected_ref": result.selected_ref,
            }
        )
    if (
        not all(isinstance(ref, str) and ref in nodes and ref.startswith("r") for ref in outputs)
        or len(outputs) != len(set(outputs))
    ):
        raise PipelineError("Short planner output reference is invalid")
    return {
        "pipeline_version": SHORT_CALCULATOR_PIPELINE_VERSION,
        "metric_definition_id": plan["metric_id"],
        "catalog_definition": METRIC_CATALOG[plan["metric_id"]],
        "selected_sources": selected,
        "steps": executed,
        "outputs": [
            {"result_id": ref, "value": str(nodes[ref].value), "selected_ref": nodes[ref].selected_ref}
            for ref in outputs
        ],
    }


def run_short_calculator_qa(
    *,
    question: dict[str, str],
    blocks: list[dict[str, Any]],
    generator: StructuredGenerator,
    num_ctx: int,
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "planner_call": "NOT_STARTED",
        "format_validation": "NOT_STARTED",
        "reference_validation": "NOT_STARTED",
        "arithmetic_execution": "NOT_STARTED",
        "answerer_call": "NOT_STARTED",
        "answer_contract_validation": "NOT_STARTED",
    }
    prepared = prepare_short_planner_contract(
        question=question, blocks=blocks, num_ctx=num_ctx
    )
    try:
        plan_generation = generator.generate_structured(
            stage="calculator_short_plan",
            instructions=SHORT_PLAN_INSTRUCTIONS,
            input_text=prepared["input_text"],
            max_output_tokens=SHORT_PLANNER_MAX_OUTPUT_TOKENS,
            response_schema=prepared["schema"],
        )
        trace["planner_call"] = "COMPLETED"
        plan = _json_object(
            plan_generation.text, {"metric_id", "inputs", "steps", "outputs"}
        )
        trace["format_validation"] = "PASSED"
        try:
            calculation = execute_short_plan(plan, prepared["registry"])
        except PipelineError as error:
            if "arithmetic failed" in str(error).lower():
                trace["reference_validation"] = "PASSED"
                trace["arithmetic_execution"] = "FAILED"
            else:
                trace["reference_validation"] = "FAILED"
            raise
        trace["reference_validation"] = "PASSED"
        trace["arithmetic_execution"] = "PASSED"
        selected_ids = list(
            dict.fromkeys(row["short_id"] for row in calculation["selected_sources"])
        )
        output_ids = [row["result_id"] for row in calculation["outputs"]]
        answer_schema = short_answer_schema(selected_ids, output_ids)
        answer_input = json.dumps(
            {
                "question": question["question"],
                "metric_id": calculation["metric_definition_id"],
                "metric_definition": calculation["catalog_definition"],
                "selected_sources": [
                    {
                        **row["planner_view"],
                        "role": row["role"],
                    }
                    for row in calculation["selected_sources"]
                ],
                "program_steps": calculation["steps"],
                "program_outputs": calculation["outputs"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        answer_generation = generator.generate_structured(
            stage="calculator_short_answer",
            instructions=SHORT_ANSWER_INSTRUCTIONS,
            input_text=answer_input,
            max_output_tokens=SHORT_ANSWER_MAX_OUTPUT_TOKENS,
            response_schema=answer_schema,
        )
        trace["answerer_call"] = "COMPLETED"
        answer = _json_object(
            answer_generation.text,
            {"conclusion", "explanation", "calculations", "sources", "results"},
        )
        if (
            not answer["sources"]
            or set(answer["sources"]) - set(selected_ids)
            or not answer["results"]
            or set(answer["results"]) - set(output_ids)
        ):
            raise PipelineError("Short answer cited unavailable sources or results")
        trace["answer_contract_validation"] = "PASSED"
    except Exception as error:
        if trace["planner_call"] == "NOT_STARTED" and getattr(
            generator, "call_count", 0
        ):
            trace["planner_call"] = "FAILED"
        elif trace["format_validation"] == "NOT_STARTED" and trace["planner_call"] == "COMPLETED":
            trace["format_validation"] = "FAILED"
        elif trace["reference_validation"] == "NOT_STARTED" and trace["format_validation"] == "PASSED":
            trace["reference_validation"] = "FAILED"
        elif trace["answerer_call"] == "NOT_STARTED" and trace["arithmetic_execution"] == "PASSED":
            trace["answerer_call"] = "FAILED"
        elif trace["answer_contract_validation"] == "NOT_STARTED" and trace["answerer_call"] == "COMPLETED":
            trace["answer_contract_validation"] = "FAILED"
        raise ShortCalculatorError(str(error), trace) from error
    source_to_original = {
        row["short_id"]: row["original_source_id"] for row in prepared["registry"]
    }
    return {
        "question_id": question["question_id"],
        "pipeline_version": SHORT_CALCULATOR_PIPELINE_VERSION,
        "candidate_count": prepared["candidate_count"],
        "candidate_reduction": prepared["candidate_reduction"],
        "token_estimate": prepared["token_estimate"],
        "source_registry": prepared["registry"],
        "short_to_original_source_id": source_to_original,
        "plan": plan,
        "calculation": calculation,
        "answer": answer,
        "answer_text": "\n".join(
            [answer["conclusion"], answer["explanation"], *answer["calculations"]]
        ).strip(),
        "stage_status": trace,
        "prompt_versions": {
            "planner": SHORT_PLAN_PROMPT_VERSION,
            "answerer": SHORT_ANSWER_PROMPT_VERSION,
        },
        "call_usage": {
            "planner": plan_generation.usage,
            "answerer": answer_generation.usage,
        },
        "dependency_edges": [
            *[
                {
                    "from": source_to_original[ref],
                    "via_short_id": ref,
                    "to": step["result_id"],
                    "kind": "current_source_calculator_operand",
                }
                for step in calculation["steps"]
                for ref in step["operand_refs"]
                if ref.startswith("s")
            ],
            *[
                {"from": ref, "to": step["result_id"], "kind": "calculator_result_operand"}
                for step in calculation["steps"]
                for ref in step["operand_refs"]
                if ref.startswith("r")
            ],
            *[
                {
                    "from": result_id,
                    "to": f"answer:{question['question_id']}",
                    "kind": "answer_declared_program_result",
                }
                for result_id in answer["results"]
            ],
        ],
    }
