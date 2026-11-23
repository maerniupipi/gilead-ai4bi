"""Minimal xlsx read/write for the eval runner.

The customer sheet only needs string cells. We parse shared strings and write
inline strings so we do not take a spreadsheet dependency.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_MAIN = {"m": NS_MAIN}
_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")
_INVALID_SHEET = re.compile(r"[\[\]:*?/\\]")
QUESTION_HEADER = "问题"
CATEGORY_HEADER = "问题分类"
RESULT_HEADERS = ("澄清选项", "最终sql", "实验室选择", "最终结果", "持续时间")
QUEUE_DROP_HEADERS = RESULT_HEADERS + ("百炼召回", "状态", "运行ID")
MAX_WORKBOOK_BYTES = 12 * 1024 * 1024
MAX_SHEETS = 16
MAX_ROWS = 5_000


@dataclass(frozen=True)
class EvalRow:
    row_number: int
    values: dict[str, str]


@dataclass(frozen=True)
class EvalSheet:
    name: str
    headers: tuple[str, ...]
    rows: tuple[EvalRow, ...]

    def questions(self) -> tuple[EvalRow, ...]:
        return tuple(row for row in self.rows if (row.values.get(QUESTION_HEADER) or "").strip())


@dataclass(frozen=True)
class EvalWorkbook:
    filename: str
    sheets: tuple[EvalSheet, ...]


def parse_xlsx(data: bytes, *, filename: str = "workbook.xlsx") -> EvalWorkbook:
    if len(data) > MAX_WORKBOOK_BYTES:
        raise ValueError("工作簿超过 12MB 上限")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("不是有效的 xlsx 文件") from exc
    with archive:
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("xlsx 缺少 workbook.xml")
        shared = _shared_strings(archive)
        sheets = _sheet_targets(archive)
        parsed: list[EvalSheet] = []
        for name, target in sheets[:MAX_SHEETS]:
            if target not in names:
                continue
            parsed.append(_parse_sheet(archive.read(target), name=name, shared=shared))
    if not parsed:
        raise ValueError("工作簿里没有可读取的工作表")
    return EvalWorkbook(filename=filename or "workbook.xlsx", sheets=tuple(parsed))


def dump_xlsx(workbook: EvalWorkbook) -> bytes:
    buffer = io.BytesIO()
    sheets = workbook.sheets[:MAX_SHEETS]
    if not sheets:
        raise ValueError("没有可导出的工作表")
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(sheets)))
        archive.writestr("_rels/.rels", _package_rels())
        archive.writestr("xl/workbook.xml", _workbook_xml(sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, sheet in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheet))
    return buffer.getvalue()


def workbook_to_payload(workbook: EvalWorkbook) -> dict[str, Any]:
    return {
        "filename": workbook.filename,
        "sheets": [
            {
                "name": sheet.name,
                "headers": list(sheet.headers),
                "question_count": len(sheet.questions()),
                "rows": [
                    {"row": row.row_number, "values": dict(row.values)} for row in sheet.questions()
                ],
            }
            for sheet in workbook.sheets
        ],
    }


def workbook_to_queue_payload(workbook: EvalWorkbook) -> dict[str, Any]:
    """Parse response for the eval runner: questions only, no previous SQL/answers."""
    payload = workbook_to_payload(workbook)
    drop = set(QUEUE_DROP_HEADERS)
    for sheet in payload["sheets"]:
        for row in sheet["rows"]:
            values = row.get("values") or {}
            row["values"] = {key: value for key, value in values.items() if key not in drop}
    return payload


def workbook_from_payload(payload: dict[str, Any]) -> EvalWorkbook:
    filename = str(payload.get("filename") or "评测结果.xlsx").strip() or "评测结果.xlsx"
    raw_sheets = payload.get("sheets")
    if not isinstance(raw_sheets, list) or not raw_sheets:
        raise ValueError("导出内容缺少 sheets")
    sheets: list[EvalSheet] = []
    for item in raw_sheets[:MAX_SHEETS]:
        if not isinstance(item, dict):
            continue
        name = _safe_sheet_name(str(item.get("name") or "评测"))
        headers = _headers_from(item.get("headers"))
        rows: list[EvalRow] = []
        raw_rows = item.get("rows")
        if not isinstance(raw_rows, list):
            continue
        for index, raw in enumerate(raw_rows[:MAX_ROWS], start=2):
            if not isinstance(raw, dict):
                continue
            values = raw.get("values")
            if not isinstance(values, dict):
                continue
            mapped = {header: str(values.get(header) or "") for header in headers}
            if not any(mapped.values()):
                continue
            row_number = raw.get("row")
            number = int(row_number) if isinstance(row_number, int) else index
            rows.append(EvalRow(row_number=number, values=mapped))
        if headers:
            sheets.append(EvalSheet(name=name, headers=headers, rows=tuple(rows)))
    if not sheets:
        raise ValueError("没有可导出的行")
    return EvalWorkbook(filename=filename, sheets=tuple(sheets))


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("m:si", _MAIN):
        texts = [node.text or "" for node in item.iter(f"{{{NS_MAIN}}}t")]
        values.append("".join(texts))
    return values


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rels = {
        node.attrib["Id"]: node.attrib["Target"]
        for node in rels_root
        if "Id" in node.attrib and "Target" in node.attrib
    }
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("m:sheets/m:sheet", _MAIN):
        name = sheet.attrib.get("name") or f"Sheet{len(sheets) + 1}"
        rid = sheet.attrib.get(f"{{{NS_OFFICE_REL}}}id") or ""
        target = rels.get(rid, "")
        if not target:
            continue
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        sheets.append((name, target))
    return sheets


def _parse_sheet(raw: bytes, *, name: str, shared: list[str]) -> EvalSheet:
    root = ET.fromstring(raw)
    grid: dict[int, dict[int, str]] = {}
    max_col = 0
    for row in root.findall("m:sheetData/m:row", _MAIN):
        number = int(row.attrib.get("r") or 0)
        if number < 1 or number > MAX_ROWS:
            continue
        for cell in row.findall("m:c", _MAIN):
            column, _ = _split_ref(cell.attrib.get("r") or "")
            if column < 0:
                continue
            max_col = max(max_col, column)
            grid.setdefault(number, {})[column] = _cell_text(cell, shared)
    if not grid:
        return EvalSheet(name=name, headers=(), rows=())
    header_row = min(grid)
    header_cells = grid.get(header_row, {})
    used_columns: list[int] = []
    headers: list[str] = []
    seen: dict[str, int] = {}
    for column in range(max_col + 1):
        label = (header_cells.get(column) or "").strip()
        if not label:
            continue
        count = seen.get(label, 0) + 1
        seen[label] = count
        headers.append(label if count == 1 else f"{label}_{count}")
        used_columns.append(column)
    if not headers:
        return EvalSheet(name=name, headers=(), rows=())
    if QUESTION_HEADER not in headers:
        raise ValueError(f"工作表「{name}」缺少「问题」列")
    category_index = headers.index(CATEGORY_HEADER) if CATEGORY_HEADER in headers else None
    rows: list[EvalRow] = []
    last_category = ""
    for number in sorted(row for row in grid if row > header_row):
        values = {
            header: (grid.get(number, {}).get(column) or "").strip()
            for header, column in zip(headers, used_columns)
        }
        if category_index is not None:
            category = values.get(CATEGORY_HEADER, "")
            if category:
                last_category = category
            elif values.get(QUESTION_HEADER) and last_category:
                values[CATEGORY_HEADER] = last_category
        if not any(values.values()):
            continue
        rows.append(EvalRow(row_number=number, values=values))
    return EvalSheet(name=name, headers=tuple(headers), rows=tuple(rows))


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t")
    if kind == "s":
        value = cell.find("m:v", _MAIN)
        if value is not None and (value.text or "").isdigit():
            index = int(value.text or 0)
            if 0 <= index < len(shared):
                return shared[index]
        return ""
    if kind == "inlineStr":
        inline = cell.find("m:is", _MAIN)
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.iter(f"{{{NS_MAIN}}}t"))
    if kind == "b":
        value = cell.find("m:v", _MAIN)
        return "TRUE" if (value is not None and value.text == "1") else "FALSE"
    value = cell.find("m:v", _MAIN)
    return value.text if value is not None and value.text else ""


def _split_ref(ref: str) -> tuple[int, int]:
    match = _CELL_REF.match(ref)
    if not match:
        return -1, -1
    letters, number = match.group(1), match.group(2)
    column = 0
    for char in letters:
        column = column * 26 + (ord(char) - 64)
    return column - 1, int(number)


def _col_letter(index: int) -> str:
    index += 1
    letters = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _headers_from(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        return (CATEGORY_HEADER, QUESTION_HEADER, *RESULT_HEADERS)
    headers: list[str] = []
    for item in raw:
        label = str(item or "").strip()
        if label and label not in headers:
            headers.append(label)
    for required in (QUESTION_HEADER, *RESULT_HEADERS):
        if required not in headers:
            headers.append(required)
    if CATEGORY_HEADER not in headers:
        headers.insert(0, CATEGORY_HEADER)
    return tuple(headers)


def _safe_sheet_name(name: str) -> str:
    clean = _INVALID_SHEET.sub(" ", name).strip() or "评测"
    return clean[:31]


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _content_types(sheet_count: int) -> str:
    overrides = "\n".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    rels_type = "application/vnd.openxmlformats-package.relationships+xml"
    sheet_main = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    styles_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Types xmlns="{NS_CT}">'
        f'<Default Extension="rels" ContentType="{rels_type}"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{sheet_main}"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{styles_type}"/>'
        f"{overrides}</Types>"
    )


def _package_rels() -> str:
    office = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{NS_REL}">'
        f'<Relationship Id="rId1" Type="{office}" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheets: tuple[EvalSheet, ...] | list[EvalSheet]) -> str:
    items = []
    for index, sheet in enumerate(sheets, start=1):
        name = _xml(_safe_sheet_name(sheet.name))
        items.append(f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_OFFICE_REL}">'
        f"<sheets>{''.join(items)}</sheets></workbook>"
    )


def _workbook_rels(sheet_count: int) -> str:
    items = [
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    ]
    items.append(
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{NS_REL}">{"".join(items)}</Relationships>'
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<styleSheet xmlns="{NS_MAIN}">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font>'
        "</fonts>"
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid">'
        '<fgColor rgb="FF8A174D"/><bgColor indexed="64"/>'
        "</patternFill></fill>"
        "</fills>"
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="3">'
        "<xf/>"
        '<xf fontId="1" fillId="2" applyFont="1" applyFill="1"/>'
        '<xf applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
        "</cellXfs>"
        "</styleSheet>"
    )


def _sheet_xml(sheet: EvalSheet) -> str:
    headers = list(sheet.headers) or [QUESTION_HEADER, *RESULT_HEADERS]
    rows_xml = [_row_xml(1, headers, style=1)]
    for offset, row in enumerate(sheet.rows):
        values = [row.values.get(header, "") for header in headers]
        rows_xml.append(_row_xml(offset + 2, values, style=2))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{NS_MAIN}">'
        f"<sheetData>{''.join(rows_xml)}</sheetData></worksheet>"
    )


def _row_xml(number: int, values: list[str], *, style: int) -> str:
    cells = []
    for index, value in enumerate(values):
        ref = f"{_col_letter(index)}{number}"
        text = _xml(_sanitize(value))
        cells.append(
            f'<c r="{ref}" t="inlineStr" s="{style}">'
            f'<is><t xml:space="preserve">{text}</t></is></c>'
        )
    return f'<row r="{number}">{"".join(cells)}</row>'


def _sanitize(value: str) -> str:
    return "".join(char for char in value if ord(char) >= 32 or char in "\n\t")
