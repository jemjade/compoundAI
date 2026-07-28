"""Canonical 표 투영, 페이지 지표, 안전한 CSV Cell을 검증한다."""

from app.services.comparison_service import csv_safe, extract_tables, page_text_lengths


def test_extract_tables_and_page_lengths_from_canonical_document() -> None:
    canonical = {
        "pages": [
            {
                "page_number": 1,
                "text": "page one",
                "blocks": [
                    {"id": "p1", "type": "paragraph", "text": "ignored"},
                    {
                        "id": "t1",
                        "type": "table",
                        "page_number": 1,
                        "text": "A B",
                        "cells": [
                            {
                                "row": 0,
                                "column": 0,
                                "row_span": 1,
                                "column_span": 1,
                                "text": "A",
                            }
                        ],
                    },
                ],
            },
            {"page_number": 2, "text": "second", "blocks": []},
        ]
    }

    tables = extract_tables(canonical)

    assert [table["id"] for table in tables] == ["t1"]
    assert tables[0]["cells"][0]["text"] == "A"
    assert page_text_lengths(canonical) == [8, 6]


def test_csv_safe_prevents_spreadsheet_formula_execution() -> None:
    assert csv_safe("=HYPERLINK('bad')") == "'=HYPERLINK('bad')"
    assert csv_safe("+command") == "'+command"
    assert csv_safe("normal") == "normal"
