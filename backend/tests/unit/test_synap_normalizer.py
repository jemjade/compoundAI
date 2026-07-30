"""사이냅 페이지·블록·Box·표가 올바르게 정규화되는지 검증한다."""

from app.normalizers.synap_normalizer import normalize_synap_response


def test_synap_normalizer_maps_pages_blocks_tables_and_bbox() -> None:
    canonical = normalize_synap_response(
        {
            "result": {
                "full_text": "계약서\n홍길동",
                "markdown": "# 계약서\n홍길동",
                "pages": [
                    {
                        "page": 1,
                        "width": 100,
                        "height": 200,
                        "blocks": [
                            {
                                "id": "title-1",
                                "type": "title",
                                "text": "계약서",
                                "bbox": [1, 2, 50, 20],
                                "confidence": 0.99,
                            },
                            {
                                "type": "table",
                                "cells": [
                                    {
                                        "row": 0,
                                        "column": 0,
                                        "text": "이름",
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        },
        document_id="document",
        run_id="run",
        parser_name="Synap",
        parser_version="1",
        parser_config={},
    )

    assert canonical.full_text == "계약서\n홍길동"
    assert canonical.pages[0].blocks[0].bbox.x1 == 1
    assert canonical.pages[0].blocks[1].type == "table"
    assert canonical.pages[0].blocks[1].cells[0].text == "이름"


def test_synap_normalizer_extracts_nested_chat_contents() -> None:
    canonical = normalize_synap_response(
        {
            "result": {
                "full_text": "",
                "pages": [
                    {
                        "page_number": 1,
                        "type": "div",
                        "contents": [
                            {
                                "type": "div",
                                "page_index": 0,
                                "contents": [
                                    {
                                        "type": "text",
                                        "contents": [
                                            {
                                                "type": "p",
                                                "contents": ["첫 번째 문장"],
                                            }
                                        ],
                                    },
                                    {
                                        "type": "text",
                                        "contents": [
                                            {
                                                "type": "p",
                                                "contents": ["두 번째 문장"],
                                            }
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        },
        document_id="document",
        run_id="run",
        parser_name="Synap Chat",
        parser_version="1",
        parser_config={},
    )

    assert canonical.full_text == "첫 번째 문장\n두 번째 문장"
    assert canonical.pages[0].text == "첫 번째 문장\n두 번째 문장"
    assert canonical.pages[0].blocks[0].text == "첫 번째 문장\n두 번째 문장"
