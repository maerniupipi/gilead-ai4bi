"""Extract table snapshots from the server's saved final answer."""

from __future__ import annotations

from html.parser import HTMLParser

from markdown_it import MarkdownIt

from xiaoying_quick.application.charts.analysis_metrics import data_payload

# Keep table indexing aligned with the answer renderer's allowed HTML elements.
_ANSWER_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "del",
    "ul",
    "ol",
    "li",
    "blockquote",
    "code",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "a",
    "sup",
    "span",
    "div",
}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.stack: list[dict] = []
        self.heading = ""
        self.heading_parts: list[str] | None = None
        self.suppressed_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.suppressed_depth or tag not in _ANSWER_TAGS:
            if tag not in _VOID_TAGS:
                self.suppressed_depth += 1
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self.heading_parts = []
        if tag == "table":
            table = {
                "title": self.heading or f"回答数据表 {len(self.tables) + 1}",
                "columns": [],
                "rows": [],
                "row": None,
                "cell": None,
                "header": False,
            }
            self.tables.append(table)
            self.stack.append(table)
        if not self.stack:
            return
        current = self.stack[-1]
        if tag == "tr":
            current.update(row=[], header=False)
        elif tag in {"th", "td"}:
            current["cell"] = []
            current["header"] = current["header"] or tag == "th"
        elif tag == "br":
            self.handle_data("\n")

    def handle_data(self, data):
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        for table in self.stack:
            if table["cell"] is not None:
                table["cell"].append(data)

    def handle_endtag(self, tag):
        if self.suppressed_depth:
            if tag not in _VOID_TAGS:
                self.suppressed_depth -= 1
            return
        if tag in {"h1", "h2", "h3", "h4"} and self.heading_parts is not None:
            self.heading = "".join(self.heading_parts).strip()[:120]
            self.heading_parts = None
        if not self.stack:
            return
        current = self.stack[-1]
        if tag in {"th", "td"} and current["cell"] is not None:
            if current["row"] is not None:
                current["row"].append("".join(current["cell"]).strip())
            current["cell"] = None
        elif tag == "tr" and current["row"] is not None:
            if not current["columns"] and current["header"]:
                current["columns"] = current["row"]
            else:
                current["rows"].append(current["row"])
            current["row"] = None
        elif tag == "table":
            self.stack.pop()


def answer_tables(markdown: str) -> list[dict]:
    parser = _TableParser()
    parser.feed(
        MarkdownIt("commonmark", {"html": True, "breaks": True}).enable("table").render(markdown)
    )
    result = []
    for table in parser.tables:
        width = max([len(table["columns"]), *(len(row) for row in table["rows"])], default=0)
        columns = table["columns"] or [f"列 {index + 1}" for index in range(width)]
        columns = [*columns, *(f"列 {index + 1}" for index in range(len(columns), width))]
        rows = [row + [None] * (width - len(row)) for row in table["rows"]]
        result.append({"title": table["title"], "data": data_payload(columns, rows, [])})
    return result
