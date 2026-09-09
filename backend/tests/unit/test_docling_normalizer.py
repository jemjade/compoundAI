"""DoclingDocument structure and provenance must survive canonical normalization."""

from app.normalizers.docling_normalizer import normalize_docling_document


def test_docling_table_cells_keep_ids_headers_and_coordinates() -> None:
    raw = {
        "schema_name": "DoclingDocument",
        "version": "1.10.0",
        "origin": {"filename": "sample.pdf"},
        "pages": {"5": {"page_no": 5, "size": {"width": 600, "height": 800}}},
        "body": {
            "children": [{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}],
        },
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "section_header",
                "text": "($ in millions)",
                "content_layer": "body",
                "prov": [
                    {
                        "page_no": 5,
                        "bbox": {
                            "l": 10,
                            "t": 790,
                            "r": 200,
                            "b": 770,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
            }
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "content_layer": "body",
                "prov": [
                    {
                        "page_no": 5,
                        "bbox": {
                            "l": 10,
                            "t": 700,
                            "r": 500,
                            "b": 300,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
                "data": {
                    "table_cells": [
                        {
                            "start_row_offset_idx": 0,
                            "start_col_offset_idx": 1,
                            "row_span": 1,
                            "col_span": 1,
                            "text": "2023",
                            "column_header": True,
                            "row_header": False,
                            "row_section": False,
                            "fillable": False,
                            "bbox": {
                                "l": 300,
                                "t": 10,
                                "r": 350,
                                "b": 30,
                                "coord_origin": "TOPLEFT",
                            },
                        },
                        {
                            "start_row_offset_idx": 1,
                            "start_col_offset_idx": 0,
                            "row_span": 1,
                            "col_span": 1,
                            "text": "Revenue",
                            "column_header": False,
                            "row_header": True,
                            "row_section": False,
                            "fillable": False,
                            "bbox": {
                                "l": 10,
                                "t": 40,
                                "r": 100,
                                "b": 60,
                                "coord_origin": "TOPLEFT",
                            },
                        },
                    ]
                },
            }
        ],
        "groups": [],
    }

    canonical = normalize_docling_document(
        raw,
        document_id="doc",
        run_id="run",
        parser_name="Docling",
        parser_version="2.126.0",
        parser_config={"device": "cpu"},
    )

    assert canonical.schema_version == "1.1"
    assert canonical.pages[0].page_number == 5
    assert canonical.pages[0].width == 600
    table = canonical.pages[0].blocks[1]
    assert table.id == "p5:tables/0"
    assert table.text == " | 2023\nRevenue | "
    assert table.cells[0].id == "#/tables/0/data/table_cells/0"
    assert table.cells[0].attributes["column_header"] is True
    assert table.cells[0].attributes["coordinate_origin"] == "TOPLEFT"
    assert table.cells[0].bbox is not None
    assert table.attributes["coordinate_origin"] == "BOTTOMLEFT"
    assert canonical.metadata["docling_document_version"] == "1.10.0"
