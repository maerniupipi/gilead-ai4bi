"""File readers check table pagination, Unicode text and spreadsheet cell types."""

from __future__ import annotations

import io

from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from xiaoying_quick.infrastructure.document_export import _ppt_text_pages, write_document


def test_ppt_prose_pagination_accounts_for_many_short_paragraphs_and_cjk_wrapping():
    paragraphs = [f"经营发现{index}，按同口径核验销售与目标。" for index in range(30)]
    paragraphs.append("详细分析" * 300)
    pages = _ppt_text_pages(paragraphs)
    assert len(pages) >= 4
    assert all(len(page.splitlines()) <= 13 for page in pages)
    assert "".join(pages).replace("\n", "") == "".join(paragraphs)


def test_wide_tables_paginate_without_dropping_excel_rows_or_running_formulas():
    columns = ["记录", *[f"业务字段{index}" for index in range(19)]]
    rows = [
        [f"记录{index}", index, '=HYPERLINK("https://example.com")', *range(17)]
        for index in range(120)
    ]
    document = {
        "title": "医药宽表验收",
        "subtitle": "模拟数据",
        "sections": [
            {
                "id": "table",
                "kind": "table",
                "title": "城市与产品数据",
                "data": {
                    "columns": columns,
                    "rows": rows,
                    "row_count": 120,
                },
            }
        ],
    }
    xlsx = write_document(document, "xlsx", {})
    workbook = load_workbook(io.BytesIO(xlsx))
    data = list(workbook.active.values)
    assert any(row[0] == "记录119" for row in data)
    formula_cell = next(cell for row in workbook.active for cell in row if cell.value == rows[0][2])
    assert formula_cell.data_type == "s"
    pdf = PdfReader(io.BytesIO(write_document(document, "pdf", {})))
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "前100行" in text and "记录119" not in text
    assert "业务字段18" in text
    assert all(page.extract_text().strip() for page in pdf.pages)
    deck = Presentation(io.BytesIO(write_document(document, "pptx", {})))
    assert len(deck.slides) > 8
    tables = [shape.table for slide in deck.slides for shape in slide.shapes if shape.has_table]
    assert tables and all(len(table.columns) <= 7 for table in tables)
    assert any(
        "业务字段18" in cell.text for table in tables for row in table.rows for cell in row.cells
    )
