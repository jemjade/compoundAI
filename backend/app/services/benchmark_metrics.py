"""Ground Truth 대비 문서 Parsing·비식별화 정량 지표 계산."""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from diff_match_patch import diff_match_patch

EVALUATOR_VERSION = "1.0.0"


def normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(normalized.split())


def edit_distance(base: str, target: str) -> int:
    """diff-match-patch의 Levenshtein 정의로 Unicode 편집 거리를 계산한다."""
    if base == target:
        return 0
    differ = diff_match_patch()
    differ.Diff_Timeout = 0
    operations = differ.diff_main(base, target, checklines=True)
    return int(differ.diff_levenshtein(operations))


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    if precision is None or recall is None or precision + recall == 0:
        f1 = 0.0 if tp + fp + fn else None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _pages(document: dict[str, Any]) -> list[dict[str, Any]]:
    value = document.get("pages")
    return [page for page in value if isinstance(page, dict)] if isinstance(value, list) else []


def _blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for page_index, page in enumerate(_pages(document), start=1):
        page_number = int(page.get("page_number", page_index))
        page_blocks = page.get("blocks")
        if not isinstance(page_blocks, list):
            continue
        for block_index, block in enumerate(page_blocks):
            if not isinstance(block, dict):
                continue
            blocks.append(
                {
                    **block,
                    "_page_number": page_number,
                    "_source_index": block_index,
                }
            )
    return blocks


def _bbox(block: dict[str, Any]) -> tuple[float, float, float, float] | None:
    value = block.get("bbox", block.get("bounding_box"))
    if isinstance(value, list) and len(value) == 4:
        coordinates = value
    elif isinstance(value, dict) and {"x1", "y1", "x2", "y2"} <= value.keys():
        coordinates = [value["x1"], value["y1"], value["x2"], value["y2"]]
    else:
        return None
    try:
        x1, y1, x2, y2 = (float(item) for item in coordinates)
    except (TypeError, ValueError):
        return None
    return (x1, y1, x2, y2) if x2 >= x1 and y2 >= y1 else None


def _iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    intersection_width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    intersection_height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = intersection_width * intersection_height
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _layout_metrics(
    ground_truth: dict[str, Any],
    prediction: dict[str, Any],
) -> tuple[dict[str, float | None], dict[str, int | float]]:
    gt_blocks = [block for block in _blocks(ground_truth) if _bbox(block) is not None]
    pred_blocks = [block for block in _blocks(prediction) if _bbox(block) is not None]
    candidates: list[tuple[float, int, int]] = []
    for gt_index, gt_block in enumerate(gt_blocks):
        for pred_index, pred_block in enumerate(pred_blocks):
            if gt_block.get("_page_number") != pred_block.get("_page_number") or gt_block.get(
                "type"
            ) != pred_block.get("type"):
                continue
            overlap = _iou(_bbox(gt_block), _bbox(pred_block))  # type: ignore[arg-type]
            if overlap >= 0.5:
                candidates.append((overlap, gt_index, pred_index))
    matches: list[float] = []
    used_gt: set[int] = set()
    used_pred: set[int] = set()
    for overlap, gt_index, pred_index in sorted(candidates, reverse=True):
        if gt_index in used_gt or pred_index in used_pred:
            continue
        used_gt.add(gt_index)
        used_pred.add(pred_index)
        matches.append(overlap)
    precision, recall, f1 = _f1(
        len(matches),
        len(pred_blocks) - len(matches),
        len(gt_blocks) - len(matches),
    )
    return (
        {
            "layout_precision_iou50": precision,
            "layout_recall_iou50": recall,
            "layout_f1_iou50": f1,
            "layout_mean_iou": sum(matches) / len(matches) if matches else None,
        },
        {
            "layout_ground_truth_blocks": len(gt_blocks),
            "layout_prediction_blocks": len(pred_blocks),
            "layout_matches_iou50": len(matches),
        },
    )


def _table_blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [block for block in _blocks(document) if block.get("type") == "table"]


def _cell_map(table: dict[str, Any]) -> dict[tuple[int, int, int, int], str]:
    cells = table.get("cells")
    if not isinstance(cells, list):
        return {}
    output: dict[tuple[int, int, int, int], str] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        try:
            key = (
                int(cell.get("row", cell.get("row_index", 0))),
                int(cell.get("column", cell.get("column_index", 0))),
                int(cell.get("row_span", 1)),
                int(cell.get("column_span", cell.get("col_span", 1))),
            )
        except (TypeError, ValueError):
            continue
        output[key] = normalize_text(cell.get("text", ""))
    return output


TableTree = tuple[str, str, tuple["TableTree", ...]]


def _table_tree(table: dict[str, Any]) -> TableTree:
    rows: dict[int, list[TableTree]] = defaultdict(list)
    for (row, column, row_span, column_span), text in sorted(_cell_map(table).items()):
        rows[row].append(
            (
                f"cell:{column}:{row_span}:{column_span}",
                text,
                (),
            )
        )
    row_nodes = tuple(("row", "", tuple(cells)) for _, cells in sorted(rows.items()))
    return ("table", "", row_nodes)


def _tree_size(tree: TableTree) -> int:
    return 1 + sum(_tree_size(child) for child in tree[2])


def _tree_distance(left: TableTree, right: TableTree, *, include_content: bool) -> float:
    substitution = 0.0 if left[0] == right[0] else 1.0
    if include_content and left[0] == right[0] and left[0].startswith("cell:"):
        left_text = left[1]
        right_text = right[1]
        substitution += edit_distance(left_text, right_text) / max(
            len(left_text),
            len(right_text),
            1,
        )
    left_children = left[2]
    right_children = right[2]
    previous = [0.0]
    for child in right_children:
        previous.append(previous[-1] + _tree_size(child))
    for left_child in left_children:
        current = [previous[0] + _tree_size(left_child)]
        for right_index, right_child in enumerate(right_children, start=1):
            current.append(
                min(
                    previous[right_index] + _tree_size(left_child),
                    current[right_index - 1] + _tree_size(right_child),
                    previous[right_index - 1]
                    + _tree_distance(
                        left_child,
                        right_child,
                        include_content=include_content,
                    ),
                )
            )
        previous = current
    return substitution + previous[-1]


def _teds(left: dict[str, Any], right: dict[str, Any], *, include_content: bool) -> float:
    left_tree = _table_tree(left)
    right_tree = _table_tree(right)
    distance = _tree_distance(left_tree, right_tree, include_content=include_content)
    return max(0.0, 1 - distance / max(_tree_size(left_tree), _tree_size(right_tree), 1))


def _table_metrics(
    ground_truth: dict[str, Any],
    prediction: dict[str, Any],
) -> tuple[dict[str, float | None], dict[str, int]]:
    gt_tables = _table_blocks(ground_truth)
    pred_tables = _table_blocks(prediction)
    gt_cells: dict[tuple[int, int, int, int, int], str] = {}
    pred_cells: dict[tuple[int, int, int, int, int], str] = {}
    table_pairs = min(len(gt_tables), len(pred_tables))
    for table_index, table in enumerate(gt_tables):
        gt_cells.update({(table_index, *key): value for key, value in _cell_map(table).items()})
    for table_index, table in enumerate(pred_tables):
        pred_cells.update({(table_index, *key): value for key, value in _cell_map(table).items()})
    gt_keys = set(gt_cells)
    pred_keys = set(pred_cells)
    shared = gt_keys & pred_keys
    precision, recall, structure_f1 = _f1(
        len(shared),
        len(pred_keys - gt_keys),
        len(gt_keys - pred_keys),
    )
    content_distance = 0
    content_reference_length = 0
    for key in gt_keys | pred_keys:
        gt_text = gt_cells.get(key, "")
        pred_text = pred_cells.get(key, "")
        content_distance += edit_distance(gt_text, pred_text)
        content_reference_length += max(len(gt_text), len(pred_text))
    content_error = (
        content_distance / content_reference_length if content_reference_length else None
    )
    table_count_accuracy = (
        1 - abs(len(gt_tables) - len(pred_tables)) / max(len(gt_tables), len(pred_tables), 1)
        if gt_tables or pred_tables
        else None
    )
    table_pair_count = max(len(gt_tables), len(pred_tables))
    structure_teds_scores: list[float] = []
    content_teds_scores: list[float] = []
    for index in range(table_pair_count):
        if index >= len(gt_tables) or index >= len(pred_tables):
            structure_teds_scores.append(0.0)
            content_teds_scores.append(0.0)
            continue
        structure_teds_scores.append(
            _teds(gt_tables[index], pred_tables[index], include_content=False)
        )
        content_teds_scores.append(
            _teds(gt_tables[index], pred_tables[index], include_content=True)
        )
    return (
        {
            "table_count_accuracy": table_count_accuracy,
            "table_teds": (
                sum(content_teds_scores) / len(content_teds_scores) if content_teds_scores else None
            ),
            "table_teds_structure": (
                sum(structure_teds_scores) / len(structure_teds_scores)
                if structure_teds_scores
                else None
            ),
            "table_structure_precision": precision,
            "table_structure_recall": recall,
            "table_structure_f1": structure_f1,
            "table_content_accuracy": (
                max(0.0, 1 - content_error) if content_error is not None else None
            ),
        },
        {
            "ground_truth_tables": len(gt_tables),
            "prediction_tables": len(pred_tables),
            "matched_table_pairs": table_pairs,
            "ground_truth_cells": len(gt_keys),
            "prediction_cells": len(pred_keys),
            "matched_cells": len(shared),
        },
    )


def _reading_order_metrics(
    ground_truth: dict[str, Any],
    prediction: dict[str, Any],
) -> tuple[dict[str, float | None], dict[str, int]]:
    gt_blocks = sorted(
        _blocks(ground_truth),
        key=lambda block: (
            block["_page_number"],
            block.get("reading_order", block["_source_index"]),
        ),
    )
    pred_blocks = sorted(
        _blocks(prediction),
        key=lambda block: (
            block["_page_number"],
            block.get("reading_order", block["_source_index"]),
        ),
    )
    unmatched_gt = set(range(len(gt_blocks)))
    matched_sequence: list[int] = []
    for pred_block in pred_blocks:
        pred_text = normalize_text(pred_block.get("text", ""))
        if not pred_text:
            continue
        best_index: int | None = None
        best_score = 0.0
        for gt_index in unmatched_gt:
            gt_block = gt_blocks[gt_index]
            if gt_block["_page_number"] != pred_block["_page_number"] or gt_block.get(
                "type"
            ) != pred_block.get("type"):
                continue
            gt_text = normalize_text(gt_block.get("text", ""))
            score = (
                1.0
                if gt_text == pred_text
                else SequenceMatcher(
                    None,
                    gt_text,
                    pred_text,
                    autojunk=False,
                ).ratio()
            )
            if score > best_score:
                best_index = gt_index
                best_score = score
        if best_index is not None and best_score >= 0.6:
            unmatched_gt.remove(best_index)
            matched_sequence.append(best_index)
    inversions = sum(
        left > right
        for index, left in enumerate(matched_sequence)
        for right in matched_sequence[index + 1 :]
    )
    pair_count = len(matched_sequence) * (len(matched_sequence) - 1) // 2
    accuracy = 1 - inversions / pair_count if pair_count else None
    coverage = len(matched_sequence) / len(gt_blocks) if gt_blocks else None
    return (
        {
            "reading_order_accuracy": accuracy,
            "reading_order_coverage": coverage,
        },
        {
            "reading_order_ground_truth_blocks": len(gt_blocks),
            "reading_order_prediction_blocks": len(pred_blocks),
            "reading_order_matched_blocks": len(matched_sequence),
            "reading_order_inversions": inversions,
        },
    )


def _formula_metrics(
    ground_truth: dict[str, Any],
    prediction: dict[str, Any],
) -> tuple[dict[str, float | None], dict[str, int]]:
    gt_formulas = [
        normalize_text(block.get("latex", block.get("text", "")))
        for block in _blocks(ground_truth)
        if block.get("type") == "formula"
    ]
    pred_formulas = [
        normalize_text(block.get("latex", block.get("text", "")))
        for block in _blocks(prediction)
        if block.get("type") == "formula"
    ]
    reference = "\n".join(gt_formulas)
    predicted = "\n".join(pred_formulas)
    if not reference and not predicted:
        accuracy = None
        exact_match = None
    else:
        distance = edit_distance(reference, predicted)
        accuracy = max(0.0, 1 - distance / max(len(reference), len(predicted), 1))
        exact_match = float(reference == predicted)
    return (
        {
            "formula_accuracy": accuracy,
            "formula_exact_match": exact_match,
        },
        {
            "ground_truth_formulas": len(gt_formulas),
            "prediction_formulas": len(pred_formulas),
        },
    )


def _entity_set(payload: Any) -> set[tuple[str, int, int]]:
    if not isinstance(payload, list):
        return set()
    entities: set[tuple[str, int, int]] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            entities.add(
                (
                    str(item.get("type", item.get("label", "UNKNOWN"))),
                    int(item["start"]),
                    int(item["end"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return entities


def _pii_metrics(
    ground_truth: dict[str, Any],
    deidentification: dict[str, Any] | None,
) -> tuple[dict[str, float | None], dict[str, int]]:
    gt_entities = _entity_set(ground_truth.get("pii_entities"))
    raw_data = deidentification.get("raw_data") if isinstance(deidentification, dict) else None
    prediction_payload: Any = None
    if isinstance(raw_data, dict):
        prediction_payload = raw_data.get("entities")
        if prediction_payload is None and isinstance(raw_data.get("result"), dict):
            result = raw_data["result"]
            prediction_payload = (
                result.get("entities") or result.get("detections") or result.get("items")
            )
    pred_entities = _entity_set(prediction_payload)
    if not gt_entities and not pred_entities:
        return (
            {
                "pii_precision": None,
                "pii_recall": None,
                "pii_f1": None,
                "pii_leakage_rate": None,
                "pii_overmask_rate": None,
            },
            {"ground_truth_pii_entities": 0, "prediction_pii_entities": 0},
        )
    true_positive = len(gt_entities & pred_entities)
    precision, recall, f1 = _f1(
        true_positive,
        len(pred_entities - gt_entities),
        len(gt_entities - pred_entities),
    )
    return (
        {
            "pii_precision": precision,
            "pii_recall": recall,
            "pii_f1": f1,
            "pii_leakage_rate": 1 - recall if recall is not None else None,
            "pii_overmask_rate": 1 - precision if precision is not None else None,
        },
        {
            "ground_truth_pii_entities": len(gt_entities),
            "prediction_pii_entities": len(pred_entities),
            "matched_pii_entities": true_positive,
        },
    )


def evaluate_documents(
    ground_truth: dict[str, Any],
    prediction: dict[str, Any],
    deidentification: dict[str, Any] | None = None,
) -> tuple[dict[str, float | None], dict[str, int], dict[str, Any]]:
    """문서 전체를 평가하고 0~1 품질 지표와 원시 모수를 함께 반환한다."""
    reference_text = normalize_text(ground_truth.get("full_text", ""))
    predicted_text = normalize_text(prediction.get("full_text", ""))
    text_distance = edit_distance(reference_text, predicted_text)
    if reference_text:
        # CER = (substitutions + deletions + insertions) / reference characters.
        # 삽입 오류가 많으면 1.0을 넘을 수 있으므로 원시 CER는 Clamp하지 않는다.
        cer = text_distance / len(reference_text)
    else:
        cer = 0.0 if not predicted_text else 1.0
    bounded_text_error = text_distance / max(
        len(reference_text),
        len(predicted_text),
        1,
    )
    gt_pages = _pages(ground_truth)
    pred_pages = _pages(prediction)
    metrics: dict[str, float | None] = {
        "text_cer": cer,
        "text_accuracy": max(0.0, 1 - bounded_text_error),
        "text_exact_match": float(reference_text == predicted_text),
        "page_count_accuracy": (
            1 - abs(len(gt_pages) - len(pred_pages)) / max(len(gt_pages), len(pred_pages), 1)
            if gt_pages or pred_pages
            else None
        ),
    }
    sample_counts: dict[str, int] = {
        "ground_truth_characters": len(reference_text),
        "prediction_characters": len(predicted_text),
        "ground_truth_pages": len(gt_pages),
        "prediction_pages": len(pred_pages),
    }
    diagnostics: dict[str, Any] = {"text_edit_distance": text_distance}
    for evaluator in (
        _layout_metrics,
        _table_metrics,
        _reading_order_metrics,
        _formula_metrics,
    ):
        values, counts = evaluator(ground_truth, prediction)
        metrics.update(values)
        sample_counts.update(counts)
    pii_values, pii_counts = _pii_metrics(ground_truth, deidentification)
    metrics.update(pii_values)
    sample_counts.update(pii_counts)

    dimension_keys = (
        "text_accuracy",
        "layout_f1_iou50",
        "table_teds",
        "reading_order_accuracy",
        "formula_accuracy",
        "pii_f1",
    )
    dimension_values = [metrics[key] for key in dimension_keys if metrics.get(key) is not None]
    metrics["overall_quality"] = (
        sum(value for value in dimension_values if value is not None) / len(dimension_values)
        if dimension_values
        else None
    )
    return (
        {
            key: round(value, 6) if isinstance(value, float) and math.isfinite(value) else value
            for key, value in metrics.items()
        },
        sample_counts,
        diagnostics,
    )
