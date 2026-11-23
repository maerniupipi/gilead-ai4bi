"""Portable PPTX, XLSX and PDF files from the same resolved analysis document."""

from __future__ import annotations

import base64
import io
import math
import re
import threading
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PillowImage

from xiaoying_quick.application.document_exports import VISUAL_TABLE_ROWS
from xiaoying_quick.shared.errors import ValidationFailed

ACCENT = "B82C43"
INK = "242630"
MUTED = "727581"
PALE = "F5F5F8"
FONT_PATH = Path(__file__).parent / "export_fonts" / "NotoSansSC-Regular.ttf"
_FONT_LOCK = threading.Lock()


def decode_chart_images(document: dict, images: dict[str, str]) -> dict[str, bytes]:
    required = {section["id"] for section in document["sections"] if section.get("chart")}
    if set(images) != required:
        raise ValidationFailed("导出图表未准备完整，请重试")
    if sum(len(value) for value in images.values()) > 28_000_000:
        raise ValidationFailed("图表图片过多，请选择单项内容导出")
    decoded = {}
    for key, value in images.items():
        if not value.startswith("data:image/png;base64,") or len(value) > 2_800_000:
            raise ValidationFailed("导出图片格式或大小无效")
        try:
            raw = base64.b64decode(value.split(",", 1)[1], validate=True)
            with PillowImage.open(io.BytesIO(raw)) as image:
                width, height = image.size
                if image.format != "PNG" or not 1 <= width <= 3600 or not 1 <= height <= 2200:
                    raise ValueError("invalid dimensions")
                image.load()
                clean = io.BytesIO()
                image.convert("RGB").save(clean, format="PNG")
                decoded[key] = clean.getvalue()
        except Exception as error:
            raise ValidationFailed("图表图片无法读取，请重新导出") from error
    return decoded


def format_value(value, *, unit: str = "", percent: bool = False, scale: str = "fraction") -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            return "—"
        if percent or unit == "%":
            return f"{value * (1 if scale == 'percent' else 100):,.2f}%"
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text} {unit}".strip()


def table_note(data: dict, *, visual: bool = False) -> str:
    notes = []
    rows = data.get("rows", [])
    if data.get("query_truncated"):
        notes.append("源查询已截断，此处仅导出已返回的数据")
    elif data.get("preview_truncated"):
        notes.append(f"保存的数据表包含前{len(rows)}行")
    if visual and len(rows) > VISUAL_TABLE_ROWS:
        notes.append(f"此文档展示前{VISUAL_TABLE_ROWS}行，更多已查询数据可导出XLSX")
    if visual and any(len(str(value)) > 120 for row in rows[:VISUAL_TABLE_ROWS] for value in row):
        notes.append("长文本按版面省略，完整值见XLSX")
    return "。".join(notes)


def _tables(section: dict, *, full: bool = False) -> list[tuple[str, dict]]:
    tables = []
    data = section.get("data")
    if data and data.get("columns"):
        tables.append(("图表数据" if section.get("chart") else "数据表", data))
    if full:
        detail = section.get("query_data") or section.get("details")
        if (
            detail
            and detail.get("columns")
            and (not data or detail["columns"] != data["columns"] or detail["rows"] != data["rows"])
        ):
            tables.append(("已查询明细", detail))
    return tables


def _column_bands(columns: list[str]):
    if len(columns) <= 7:
        yield list(range(len(columns)))
        return
    yield list(range(7))
    for start in range(7, len(columns), 6):
        yield [0, *range(start, min(start + 6, len(columns)))]


def _ppt_text_pages(paragraphs: list[str]) -> list[str]:
    pages = []
    current = []
    height = 0
    for paragraph in paragraphs:
        for line in paragraph.splitlines():
            for start in range(0, len(line), 600):
                part = line[start : start + 600]
                width = sum(
                    2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in part
                )
                # Reserve room for CJK wrapping and the paragraph's own spacing.
                cost = math.ceil(width / 84) * 21 + 7
                if current and height + cost > 365:
                    pages.append("\n".join(current))
                    current = []
                    height = 0
                current.append(part)
                height += cost
    if current:
        pages.append("\n".join(current))
    return pages


def _cell(data: dict, row: list, index: int) -> str:
    column = data["columns"][index]
    config = data.get("formats", {}).get(column, {})
    return format_value(
        row[index] if index < len(row) else None,
        percent=bool(config.get("percent")),
        scale=config.get("scale", "fraction"),
    )


def export_xlsx(document: dict, images: dict[str, bytes]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.drawing.image import Image
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.worksheet import Worksheet

    workbook = Workbook(write_only=True)
    used_names = set()
    total_cells = 0
    body_font = Font(name="Microsoft YaHei", size=11, color=INK)
    header_font = Font(name="Microsoft YaHei", size=11, color="FFFFFF", bold=True)
    header_fill = PatternFill("solid", fgColor=ACCENT)
    alignment = Alignment(vertical="top", wrap_text=True)

    def sheet(title):
        base = re.sub(r"[\[\]:*?/\\]", " ", title).strip().strip("'")[:28] or "分析"
        name = base
        suffix = 1
        while name.casefold() in used_names:
            suffix += 1
            name = f"{base[:26]} {suffix}"
        used_names.add(name.casefold())
        result = workbook.create_sheet(name)
        result.sheet_view.showGridLines = False
        result.sheet_format.defaultColWidth = 24
        result.sheet_properties.pageSetUpPr.fitToPage = True
        result.page_setup.orientation = "landscape"
        result.page_setup.paperSize = Worksheet.PAPERSIZE_A4
        result.page_setup.fitToWidth = 1
        result.page_setup.fitToHeight = 0
        return result

    def cell(ws, value, *, header=False, number_format=None):
        if isinstance(value, int) and len(str(abs(value))) > 15:
            value = str(value)
        result = WriteOnlyCell(ws, value=value)
        if isinstance(value, str):
            result.data_type = "s"
        result.font = header_font if header else body_font
        result.alignment = alignment
        if header:
            result.fill = header_fill
        if number_format:
            result.number_format = number_format
        return result

    ws = None
    row_index = 0

    def append(values, *, header=False):
        nonlocal row_index
        cells = [cell(ws, value, header=header) for value in values]
        if cells and row_index < 2:
            cells[0].alignment = Alignment(wrap_text=False)
            if row_index == 0:
                cells[0].font = Font(name="Microsoft YaHei", size=16, bold=True, color=INK)
                ws.row_dimensions[1].height = 30
        ws.append(cells)
        row_index += 1

    for section in document["sections"]:
        ws = sheet(section["title"])
        if section.get("paragraphs"):
            ws.column_dimensions["A"].width = 100
        if section.get("data") and not any(
            section.get(key) for key in ("chart", "paragraphs", "kpis")
        ):
            ws.freeze_panes = "B6"
        row_index = 0
        append([section["title"]])
        append([section.get("scope") or document.get("subtitle", "")])
        for paragraph in section.get("paragraphs", []):
            for start in range(0, len(paragraph), 1000):
                ws.row_dimensions[row_index + 1].height = max(
                    25, math.ceil(len(paragraph[start : start + 1000]) / 60) * 16
                )
                append([paragraph[start : start + 1000]])
        kpis = section.get("kpis", [])
        if kpis:
            append(["指标", "数值", "单位"], header=True)
            for metric in kpis:
                value = cell(
                    ws,
                    metric.get("value"),
                    number_format="0.00%" if metric.get("unit") == "%" else "#,##0.00",
                )
                ws.append([cell(ws, metric["label"]), value, cell(ws, metric.get("unit", ""))])
                row_index += 1
        if section.get("chart"):
            append([])
            image = Image(io.BytesIO(images[section["id"]]))
            image.width = 1000
            image.height = 425
            ws.add_image(image, f"A{row_index + 1}")
            for _ in range(24):
                append([])
        for table_index, (label, data) in enumerate(_tables(section, full=True)):
            if table_index or section.get("chart") or section.get("paragraphs") or kpis:
                ws = sheet(f"{section['title']} · {label}")
                ws.freeze_panes = "B6"
                row_index = 0
                append([section["title"]])
                append([section.get("scope", "")])
            append([label])
            append([table_note(data)])
            header_row = row_index + 1
            ws.row_dimensions[header_row].height = min(
                90, max(25, math.ceil(max(map(len, data["columns"])) / 18) * 15)
            )
            append(data["columns"], header=True)
            for row in data.get("rows", []):
                total_cells += len(data["columns"])
                if total_cells > 2_000_000:
                    raise ValidationFailed("导出超过200万单元格，请缩小范围或分别导出")
                values = []
                for index, column in enumerate(data["columns"]):
                    config = data.get("formats", {}).get(column, {})
                    number_format = "#,##0.00"
                    if config.get("percent"):
                        number_format = '0.00"%"' if config.get("scale") == "percent" else "0.00%"
                    value = row[index] if index < len(row) else None
                    values.append(cell(ws, value, number_format=number_format))
                ws.append(values)
                row_index += 1
            last = get_column_letter(len(data["columns"]))
            ws.auto_filter.ref = f"A{header_row}:{last}{row_index}"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _pdf_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    with _FONT_LOCK:
        if "ExportSansSC" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ExportSansSC", str(FONT_PATH)))
    return "ExportSansSC"


def export_pdf(document: dict, images: dict[str, bytes]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        Image,
        LongTable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    font = _pdf_font()
    output = io.BytesIO()
    width, height = landscape(A4)
    page = SimpleDocTemplate(
        output,
        pagesize=(width, height),
        leftMargin=34,
        rightMargin=34,
        topMargin=32,
        bottomMargin=36,
        title=document["title"],
    )
    styles = {
        "title": ParagraphStyle(
            "title",
            fontName=font,
            fontSize=17,
            leading=23,
            textColor=colors.HexColor(f"#{INK}"),
            spaceAfter=10,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=font,
            fontSize=10,
            leading=16,
            wordWrap="CJK",
            alignment=TA_LEFT,
            spaceAfter=9,
        ),
        "small": ParagraphStyle(
            "small",
            fontName=font,
            fontSize=8,
            leading=12,
            wordWrap="CJK",
            textColor=colors.HexColor(f"#{MUTED}"),
            spaceAfter=7,
        ),
        "cell": ParagraphStyle("cell", fontName=font, fontSize=8.5, leading=12, wordWrap="CJK"),
        "head": ParagraphStyle(
            "head", fontName=font, fontSize=8.5, leading=12, wordWrap="CJK", textColor=colors.white
        ),
    }

    def paragraph(text, style="body"):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style])

    story = []
    usable = width - 68

    def heading(title, scope=""):
        if story:
            story.append(PageBreak())
        story.append(paragraph(title, "title"))
        if scope:
            story.append(paragraph(scope, "small"))

    def footer(canvas, _doc):
        if canvas.getPageNumber() > 200:
            raise ValidationFailed("PDF内容超过200页，请选择单项导出或使用XLSX")
        canvas.setStrokeColor(colors.HexColor(f"#{ACCENT}"))
        canvas.line(34, 27, width - 34, 27)
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor(f"#{MUTED}"))
        canvas.drawString(34, 16, document["title"][:65])
        canvas.drawRightString(width - 34, 16, str(canvas.getPageNumber()))

    for section in document["sections"]:
        if section.get("chart") or section.get("paragraphs") or section.get("kpis"):
            heading(section["title"], section.get("scope", ""))
        for text in section.get("paragraphs", []):
            story.append(paragraph(text))
        metrics = section.get("kpis", [])
        if metrics:
            cards = []
            for metric in metrics:
                value = format_value(metric.get("value"), unit=metric.get("unit", ""))
                cards.append(paragraph(f"{metric['label']}\n{value}"))
            rows = [cards[start : start + 4] for start in range(0, len(cards), 4)]
            for row in rows:
                row.extend([""] * (4 - len(row)))
            grid = Table(rows, colWidths=[usable / 4] * 4)
            grid.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(f"#{PALE}")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 12),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            story.extend([grid, Spacer(1, 10)])
        if section.get("chart"):
            image = Image(io.BytesIO(images[section["id"]]))
            ratio = min(
                usable / image.imageWidth, (260 if len(metrics) > 4 else 300) / image.imageHeight
            )
            image.drawWidth, image.drawHeight = image.imageWidth * ratio, image.imageHeight * ratio
            story.append(image)
        for label, data in _tables(section):
            for band_index, band in enumerate(_column_bands(data["columns"])):
                heading(f"{section['title']} · {label}", section.get("scope", ""))
                note = table_note(data, visual=True)
                if note:
                    story.append(paragraph(note, "small"))
                if len(data["columns"]) > 7:
                    story.append(
                        paragraph(f"字段分组 {band_index + 1}，首列在各组重复便于对照。", "small")
                    )
                values = [[paragraph(data["columns"][index][:100], "head") for index in band]]
                for row in data.get("rows", [])[:VISUAL_TABLE_ROWS]:
                    cells = [_cell(data, row, index) for index in band]
                    values.append(
                        [
                            paragraph(value[:119] + "…" if len(value) > 120 else value, "cell")
                            for value in cells
                        ]
                    )
                table = LongTable(values, colWidths=[usable / len(band)] * len(band), repeatRows=1)
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{ACCENT}")),
                            (
                                "ROWBACKGROUNDS",
                                (0, 1),
                                (-1, -1),
                                [colors.white, colors.HexColor(f"#{PALE}")],
                            ),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 7),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                story.append(table)
    page.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def export_pptx(document: dict, images: dict[str, bytes]) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Inches(13.333), Inches(7.5)
    presentation.core_properties.title = document["title"]

    def text(slide, x, y, w, h, value, *, size=16, color=INK, bold=False):
        shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = shape.text_frame
        frame.word_wrap = True
        frame.margin_left = frame.margin_right = 0
        frame.margin_top = frame.margin_bottom = 0
        for index, line in enumerate(str(value).split("\n")):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = line
            paragraph.font.name = "Microsoft YaHei"
            paragraph.font.size = Pt(size)
            paragraph.font.bold = bold
            paragraph.font.color.rgb = RGBColor.from_string(color)
            paragraph.space_after = Pt(7)
        return shape

    def slide(title, scope=""):
        if len(presentation.slides) >= 200:
            raise ValidationFailed("PPT超过200页，请选择单项导出或使用XLSX")
        result = presentation.slides.add_slide(presentation.slide_layouts[6])
        line = result.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(0.26), Inches(0.65), Inches(0.05)
        )
        line.fill.solid()
        line.fill.fore_color.rgb = RGBColor.from_string(ACCENT)
        line.line.fill.background()
        title_size = 24 if len(title) <= 30 else 21 if len(title) <= 70 else 16
        text(result, 0.55, 0.42, 12.2, 0.8, title, size=title_size, bold=True)
        if scope:
            text(result, 0.55, 1.25, 12.2, 0.25, scope[:150], size=10, color=MUTED)
        text(result, 0.55, 7.12, 11.5, 0.2, document["title"][:85], size=8, color=MUTED)
        text(result, 12.2, 7.1, 0.5, 0.2, str(len(presentation.slides)), size=9, color=MUTED)
        return result

    def kpis(result, metrics, top=1.65):
        for index, metric in enumerate(metrics):
            x, y = 0.55 + (index % 4) * 3.1, top + (index // 4) * 1.22
            shape = result.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(2.97), Inches(1.08)
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor.from_string(PALE)
            shape.line.fill.background()
            text(result, x + 0.16, y + 0.13, 2.65, 0.23, metric["label"], size=11, color=MUTED)
            value = format_value(metric.get("value"), unit=metric.get("unit", ""))
            text(result, x + 0.16, y + 0.48, 2.65, 0.43, value, size=18 if len(value) > 12 else 23)

    for section in document["sections"]:
        paragraphs = section.get("paragraphs", [])
        if paragraphs:
            for index, chunk in enumerate(_ppt_text_pages(paragraphs)):
                result = slide(section["title"] + (f"（续{index}）" if index else ""))
                text(result, 0.65, 1.52, 12, 5.25, chunk.strip(), size=16)
        metrics = section.get("kpis", [])
        if metrics and (not section.get("chart") or len(metrics) > 4):
            result = slide(section["title"], section.get("scope", ""))
            kpis(result, metrics)
        if section.get("chart"):
            result = slide(section["title"], section.get("scope", ""))
            has_kpis = bool(metrics) and len(metrics) <= 4
            if has_kpis:
                kpis(result, metrics, top=1.52)
            top, maximum = (2.82, 3.95) if has_kpis else (1.6, 5.12)
            image_data = images[section["id"]]
            with PillowImage.open(io.BytesIO(image_data)) as image:
                ratio = min(12.1 / image.width, maximum / image.height)
                w, h = image.width * ratio, image.height * ratio
            result.shapes.add_picture(
                io.BytesIO(image_data),
                Inches((13.333 - w) / 2),
                Inches(top),
                width=Inches(w),
                height=Inches(h),
            )
        for label, data in _tables(section):
            rows = data.get("rows", [])[:VISUAL_TABLE_ROWS]
            for band_index, band in enumerate(_column_bands(data["columns"])):
                for start in range(0, max(1, len(rows)), 14):
                    visible = rows[start : start + 14]
                    result = slide(f"{section['title']} · {label}", section.get("scope", ""))
                    table = result.shapes.add_table(
                        len(visible) + 1,
                        len(band),
                        Inches(0.55),
                        Inches(1.55),
                        Inches(12.2),
                        Inches(0.52 + 0.34 * len(visible)),
                    ).table
                    table.rows[0].height = Inches(0.52)
                    values = [[data["columns"][index] for index in band]]
                    values.extend([_cell(data, row, index) for index in band] for row in visible)
                    for ri, row in enumerate(values):
                        for ci, value in enumerate(row):
                            target = table.cell(ri, ci)
                            limit = 30 if ri == 0 else 22
                            target.text = value[: limit - 1] + "…" if len(value) > limit else value
                            target.margin_left = target.margin_right = Inches(0.07)
                            target.margin_top = target.margin_bottom = Inches(0.035)
                            target.fill.solid()
                            target.fill.fore_color.rgb = RGBColor.from_string(
                                ACCENT if ri == 0 else PALE if ri % 2 == 0 else "FFFFFF"
                            )
                            for paragraph in target.text_frame.paragraphs:
                                paragraph.font.name = "Microsoft YaHei"
                                paragraph.font.size = Pt(10.5)
                                paragraph.font.bold = ri == 0
                                paragraph.font.color.rgb = RGBColor.from_string(
                                    "FFFFFF" if ri == 0 else INK
                                )
                    note = f"第{start + 1}—{start + len(visible)}行，字段组{band_index + 1}。"
                    note += table_note(data, visual=True)
                    note += " 长文本在演示页省略，完整值见XLSX。"
                    text(result, 0.55, 6.86, 12.2, 0.2, note, size=8, color=MUTED)
    if not presentation.slides:
        result = slide(document["title"])
        text(result, 0.65, 1.6, 12, 2, "当前范围没有数据。")
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


WRITERS = {"pptx": export_pptx, "xlsx": export_xlsx, "pdf": export_pdf}


def write_document(document: dict, format_name: str, images: dict[str, str]) -> bytes:
    decoded = decode_chart_images(document, images)
    return WRITERS[format_name](document, decoded)
