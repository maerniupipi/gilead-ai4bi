"""Styled xlsx writer for full query-result downloads.

Chat only shows the first 30 rows; this workbook carries the complete set.
Colours follow the Xiaoying / AstraZeneca palette already used in the UI.
No spreadsheet library: the file is a small OOXML zip, same approach as
``eval_xlsx``.
"""

from __future__ import annotations

import io
import math
import zipfile
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_INVALID_SHEET = r'[]:*?/\\'

# AstraZeneca / Xiaoying palette (AARRGGBB as Excel expects).
AZ_PLUM = "FF8A174D"
AZ_NAVY = "FF17344B"
AZ_SOFT = "FFF6E8EF"
AZ_INK = "FF1C1418"
AZ_WHITE = "FFFFFFFF"
AZ_LINE = "FFC9B6BE"

MAX_EXPORT_ROWS = 5_000
MAX_EXPORT_COLS = 64
MAX_WORKBOOK_BYTES = 12 * 1024 * 1024

# cellXfs indices — keep in sync with ``_styles_xml``.
STYLE_TITLE = 1
STYLE_HEADER = 2
STYLE_TEXT = 3
STYLE_TEXT_ALT = 4
STYLE_INT = 5
STYLE_INT_ALT = 6
STYLE_FLOAT = 7
STYLE_FLOAT_ALT = 8


def dump_result_xlsx(
    *,
    title: str,
    summary: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    sheet_name: str = "查询结果",
) -> bytes:
    """Build a themed workbook: merged banner, header row, then every data row."""

    headers = _headers(columns)
    body = [_normalize_row(row, len(headers)) for row in rows[:MAX_EXPORT_ROWS]]
    banner = _banner(title, summary, len(body))
    last_col = _col_letter(len(headers) - 1)
    last_row = 2 + len(body)
    sheet = _sheet_xml(
        banner=banner,
        headers=headers,
        rows=body,
        last_col=last_col,
        last_row=last_row,
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types())
        archive.writestr("_rels/.rels", _package_rels())
        archive.writestr("xl/workbook.xml", _workbook_xml(sheet_name))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels())
        archive.writestr("xl/styles.xml", _styles_xml())
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    payload = buffer.getvalue()
    if len(payload) > MAX_WORKBOOK_BYTES:
        raise ValueError("导出文件超过 12MB 上限")
    return payload


def _headers(columns: Sequence[str]) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for item in columns[:MAX_EXPORT_COLS]:
        label = " ".join(str(item or "").split()) or "列"
        count = seen.get(label, 0) + 1
        seen[label] = count
        headers.append(label if count == 1 else f"{label}_{count}")
    return headers or ["结果"]


def _banner(title: str, summary: str, row_count: int) -> str:
    lines = [str(title or "").strip(), str(summary or "").strip()]
    blob = "".join(lines)
    already = f"共 {row_count} 行" in blob or f"共{row_count}行" in blob
    if not already:
        lines.append(f"完整结果共 {row_count} 行")
    return "\n".join(line for line in lines if line) or f"完整结果共 {row_count} 行"


def _normalize_row(row: Sequence[Any] | Any, width: int) -> list[Any]:
    cells = list(row) if isinstance(row, (list, tuple)) else [row]
    if len(cells) < width:
        cells.extend([None] * (width - len(cells)))
    return [_normalize_cell(cell) for cell in cells[:width]]


def _normalize_cell(cell: Any) -> Any:
    if cell is None or isinstance(cell, bool):
        return cell
    if isinstance(cell, int) and not isinstance(cell, bool):
        return cell
    if isinstance(cell, float):
        if math.isnan(cell) or math.isinf(cell):
            return str(cell)
        return cell
    if isinstance(cell, Decimal):
        if cell == cell.to_integral_value():
            return int(cell)
        return float(cell)
    if isinstance(cell, dict) and "__decimal__" in cell:
        try:
            return _normalize_cell(Decimal(str(cell["__decimal__"])))
        except Exception:  # noqa: BLE001 — fall back to the original text
            return str(cell.get("__decimal__") or "")
    if isinstance(cell, datetime):
        return cell.isoformat(sep=" ", timespec="seconds")
    if isinstance(cell, date):
        return cell.isoformat()
    text = str(cell)
    return text if len(text) <= 32_767 else text[:32_764] + "..."


def _sheet_xml(
    *,
    banner: str,
    headers: list[str],
    rows: list[list[Any]],
    last_col: str,
    last_row: int,
) -> str:
    widths = _column_widths(headers, rows)
    cols = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths, start=1)
    )
    header_cells = [
        _inline_cell(f"{_col_letter(index)}2", label, STYLE_HEADER)
        for index, label in enumerate(headers)
    ]
    data_rows = [_data_row(offset + 3, row, offset % 2 == 1) for offset, row in enumerate(rows)]
    # OOXML sequence is sheetData → autoFilter → mergeCells. Putting mergeCells
    # before autoFilter makes Excel drop the merge, so the title sits in A1 only.
    # Merged range cells besides A1 must be omitted from sheetData.
    merge_ref = f"A1:{last_col}1"
    height = _banner_height(banner, widths)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{NS_MAIN}">'
        f'<dimension ref="A1:{last_col}{last_row}"/>'
        "<sheetViews>"
        '<sheetView workbookViewId="0">'
        '<pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>'
        "</sheetView>"
        "</sheetViews>"
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<cols>{cols}</cols>"
        "<sheetData>"
        f'<row r="1" ht="{height}" customHeight="1">'
        f"{_inline_cell('A1', banner, STYLE_TITLE)}"
        "</row>"
        f'<row r="2" ht="20" customHeight="1">{"".join(header_cells)}</row>'
        f"{''.join(data_rows)}"
        "</sheetData>"
        f'<autoFilter ref="A2:{last_col}{last_row}"/>'
        f'<mergeCells count="1"><mergeCell ref="{merge_ref}"/></mergeCells>'
        "</worksheet>"
    )


def _data_row(number: int, values: list[Any], alt: bool) -> str:
    cells = []
    for index, value in enumerate(values):
        ref = f"{_col_letter(index)}{number}"
        cells.append(_value_cell(ref, value, alt))
    return f'<row r="{number}">{"".join(cells)}</row>'


def _value_cell(ref: str, value: Any, alt: bool) -> str:
    if value is None:
        style = STYLE_TEXT_ALT if alt else STYLE_TEXT
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value, bool):
        style = STYLE_TEXT_ALT if alt else STYLE_TEXT
        return _inline_cell(ref, "TRUE" if value else "FALSE", style)
    if isinstance(value, int) and not isinstance(value, bool):
        style = STYLE_INT_ALT if alt else STYLE_INT
        return f'<c r="{ref}" s="{style}" t="n"><v>{value}</v></c>'
    if isinstance(value, float):
        style = STYLE_FLOAT_ALT if alt else STYLE_FLOAT
        return f'<c r="{ref}" s="{style}" t="n"><v>{_float_xml(value)}</v></c>'
    style = STYLE_TEXT_ALT if alt else STYLE_TEXT
    return _inline_cell(ref, str(value), style)


def _float_xml(value: float) -> str:
    text = format(value, ".12g")
    return text if text not in {"nan", "inf", "-inf"} else "0"


def _inline_cell(ref: str, text: str, style: int) -> str:
    return (
        f'<c r="{ref}" t="inlineStr" s="{style}">'
        f'<is><t xml:space="preserve">{_xml(_sanitize(text))}</t></is></c>'
    )


def _column_widths(headers: list[str], rows: list[list[Any]]) -> list[str]:
    widths: list[float] = []
    sample = rows[:40]
    for index, header in enumerate(headers):
        longest = _display_width(header)
        for row in sample:
            if index < len(row) and row[index] is not None:
                longest = max(longest, _display_width(str(row[index])))
        widths.append(min(42.0, max(14.0, longest * 1.15 + 2.0)))
    minimum_total = 72.0
    total = sum(widths)
    if widths and total < minimum_total:
        extra = (minimum_total - total) / len(widths)
        widths = [min(48.0, width + extra) for width in widths]
    return [f"{width:.2f}" for width in widths]


def _banner_height(banner: str, widths: list[str]) -> str:
    usable = max(20.0, sum(float(width) for width in widths) * 1.05)
    lines = 0
    for paragraph in banner.split("\n"):
        span = max(1, _display_width(paragraph))
        lines += max(1, math.ceil(span / usable))
    return f"{min(96.0, max(36.0, lines * 16.0 + 10.0)):.1f}"


def _display_width(text: str) -> int:
    width = 0
    for char in text[:80]:
        width += 2 if ord(char) > 127 else 1
    return width


def _col_letter(index: int) -> str:
    index += 1
    letters: list[str] = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _sanitize(value: str) -> str:
    return "".join(char for char in value if ord(char) >= 32 or char in "\n\t")


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _safe_sheet_name(name: str) -> str:
    clean = "".join(" " if char in _INVALID_SHEET else char for char in name).strip()
    return (clean or "查询结果")[:31]


def _content_types() -> str:
    rels = "application/vnd.openxmlformats-package.relationships+xml"
    sheet_main = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    styles = "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"
    worksheet = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Types xmlns="{NS_CT}">'
        f'<Default Extension="rels" ContentType="{rels}"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{sheet_main}"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{styles}"/>'
        f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{worksheet}"/>'
        "</Types>"
    )


def _package_rels() -> str:
    office = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{NS_REL}">'
        f'<Relationship Id="rId1" Type="{office}" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheet_name: str) -> str:
    name = _xml(_safe_sheet_name(sheet_name))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_OFFICE_REL}">'
        f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )


def _workbook_rels() -> str:
    worksheet = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    styles = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{NS_REL}">'
        f'<Relationship Id="rId1" Type="{worksheet}" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{styles}" Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<styleSheet xmlns="{NS_MAIN}">'
        '<numFmts count="2">'
        '<numFmt numFmtId="164" formatCode="#,##0"/>'
        '<numFmt numFmtId="165" formatCode="#,##0.00"/>'
        "</numFmts>"
        '<fonts count="4">'
        '<font><sz val="11"/><color rgb="FF1C1418"/><name val="Calibri"/></font>'
        f'<font><b/><sz val="12"/><color rgb="{AZ_WHITE}"/><name val="Calibri"/></font>'
        f'<font><b/><sz val="10"/><color rgb="{AZ_WHITE}"/><name val="Calibri"/></font>'
        f'<font><sz val="10"/><color rgb="{AZ_INK}"/><name val="Calibri"/></font>'
        "</fonts>"
        '<fills count="5">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid">'
        f'<fgColor rgb="{AZ_PLUM}"/><bgColor indexed="64"/>'
        "</patternFill></fill>"
        '<fill><patternFill patternType="solid">'
        f'<fgColor rgb="{AZ_NAVY}"/><bgColor indexed="64"/>'
        "</patternFill></fill>"
        '<fill><patternFill patternType="solid">'
        f'<fgColor rgb="{AZ_SOFT}"/><bgColor indexed="64"/>'
        "</patternFill></fill>"
        "</fills>"
        '<borders count="2">'
        "<border/>"
        "<border>"
        f'<left style="thin"><color rgb="{AZ_LINE}"/></left>'
        f'<right style="thin"><color rgb="{AZ_LINE}"/></right>'
        f'<top style="thin"><color rgb="{AZ_LINE}"/></top>'
        f'<bottom style="thin"><color rgb="{AZ_LINE}"/></bottom>'
        "</border>"
        "</borders>"
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="9">'
        "<xf/>"
        # 1 title
        '<xf fontId="1" fillId="2" borderId="1" applyFont="1" applyFill="1" '
        'applyBorder="1" applyAlignment="1">'
        '<alignment wrapText="1" vertical="center" horizontal="left"/>'
        "</xf>"
        # 2 header
        '<xf fontId="2" fillId="3" borderId="1" applyFont="1" applyFill="1" applyBorder="1">'
        '<alignment wrapText="1" vertical="center"/>'
        "</xf>"
        # 3 text / 4 text alt
        '<xf fontId="3" fillId="0" borderId="1" applyFont="1" applyBorder="1"/>'
        '<xf fontId="3" fillId="4" borderId="1" applyFont="1" applyFill="1" applyBorder="1"/>'
        # 5 int / 6 int alt
        '<xf fontId="3" fillId="0" borderId="1" numFmtId="164" applyFont="1" '
        'applyBorder="1" applyNumberFormat="1"/>'
        '<xf fontId="3" fillId="4" borderId="1" numFmtId="164" applyFont="1" applyFill="1" '
        'applyBorder="1" applyNumberFormat="1"/>'
        # 7 float / 8 float alt
        '<xf fontId="3" fillId="0" borderId="1" numFmtId="165" applyFont="1" '
        'applyBorder="1" applyNumberFormat="1"/>'
        '<xf fontId="3" fillId="4" borderId="1" numFmtId="165" applyFont="1" applyFill="1" '
        'applyBorder="1" applyNumberFormat="1"/>'
        "</cellXfs>"
        "</styleSheet>"
    )


def parse_result_xlsx_meta(data: bytes) -> dict[str, Any]:
    """Test helper: pull banner, headers, row count and theme colours from a file."""

    archive = zipfile.ZipFile(io.BytesIO(data))
    with archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        styles = archive.read("xl/styles.xml").decode("utf-8")
    ns = {"m": NS_MAIN}
    merge = sheet.find("m:mergeCells/m:mergeCell", ns)
    rows = sheet.findall("m:sheetData/m:row", ns)
    banner_node = sheet.find('m:sheetData/m:row[@r="1"]/m:c/m:is/m:t', ns)
    header_nodes = sheet.findall('m:sheetData/m:row[@r="2"]/m:c/m:is/m:t', ns)
    data_rows = [row for row in rows if int(row.attrib.get("r") or 0) >= 3]
    row1 = sheet.find('m:sheetData/m:row[@r="1"]', ns)
    xml = ET.tostring(sheet, encoding="unicode")
    auto_pos = xml.find("autoFilter")
    merge_pos = xml.find("mergeCells")
    return {
        "merge": merge.attrib.get("ref") if merge is not None else "",
        "banner": "".join(banner_node.itertext()) if banner_node is not None else "",
        "headers": ["".join(node.itertext()) for node in header_nodes],
        "row_count": len(data_rows),
        "row1_cells": len(row1.findall("m:c", ns)) if row1 is not None else 0,
        "merge_after_filter": auto_pos != -1 and merge_pos > auto_pos,
        "has_plum": AZ_PLUM in styles,
        "has_navy": AZ_NAVY in styles,
        "frozen": 'ySplit="2"' in xml,
    }
