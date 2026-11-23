"""Document views of the published knowledge store, including legacy section-based imports."""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
import re
import unicodedata

from markdown_it import MarkdownIt

from .contracts import KnowledgeScope, knowledge_is_valid_at, normalize_knowledge_title

MAX_MARKDOWN_BYTES = 1024 * 1024
MAX_READ_CHARS = 6000
MARKDOWN = MarkdownIt("commonmark")


def is_markdown(title: str) -> bool:
    return title.casefold().endswith((".md", ".markdown"))


def upload_name(value: str) -> str:
    value = unicodedata.normalize("NFC", value.strip())
    if (not is_markdown(value) or not value.rsplit(".", 1)[0].strip(". ")
            or "/" in value or "\\" in value or len(value) > 200
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("请选择文件名有效的 Markdown 文件（.md 或 .markdown）")
    return value


def document_id(scope, domain_id, name):
    key = "\0".join((scope.value, domain_id or "", normalize_knowledge_title(name)))
    return "doc_" + hashlib.sha256(key.encode()).hexdigest()[:24]


@dataclass
class Document:
    id: str
    filename: str
    markdown: str
    version: int
    updated_at: datetime
    reference: bool = False

    @cached_property
    def sections(self):
        lines = self.markdown.splitlines(keepends=True)
        headings = []
        tokens = MARKDOWN.parse(self.markdown)
        for i, token in enumerate(tokens):
            if token.type == "heading_open" and token.level == 0 and token.map:
                headings.append((token.map[0], tokens[i+1].content or self.filename))
        if not headings or headings[0][0] > 0:
            headings.insert(0, (0, self.filename))
        return [(title, "".join(lines[start:end])) for (start, title), (end, _) in
                zip(headings, [*headings[1:], (len(lines), "")], strict=True)]

    def info(self):
        return {"id": self.id, "filename": self.filename, "version": self.version,
                "updated_at": self.updated_at, "reference": self.reference}

    def link(self, section):
        return f"#/knowledge?doc={self.id}&section={section}"


def published_documents(entries):
    now = datetime.now(timezone.utc)
    groups = defaultdict(list)
    uploads = {}
    for entry in entries:
        if entry.scope is KnowledgeScope.PERSONAL or not knowledge_is_valid_at(entry.valid_from, entry.valid_until, instant=now):
            continue
        seeded = entry.id.startswith("seed_") and entry.published_by == "system-seed"
        name = entry.title.split(" · ", 1)[0] if seeded else entry.title
        key = document_id(entry.scope, entry.domain_id, name)
        if seeded:
            groups[key].append((name, entry))
        else:
            uploads[key] = Document(key, name, entry.content, entry.version, entry.published_at,
                                    reference=entry.scope is not KnowledgeScope.BUSINESS)
    documents = dict(uploads)
    for key, group in groups.items():
        if key in uploads:
            continue
        group.sort(key=lambda pair: (not pair[1].title.endswith(" · 概览"), pair[1].published_at, pair[1].id))
        name = group[0][0]
        entries = [row for _, row in group]
        documents[key] = Document(key, name, "\n\n".join(row.content for row in entries),
                                  max(row.version for row in entries), max(row.published_at for row in entries),
                                  reference=name in {"数据字典.md", "实验室总索引.md"} or entries[0].scope is not KnowledgeScope.BUSINESS)
    return documents


def _terms(text):
    result = set()
    for word in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", unicodedata.normalize("NFKC", text).casefold()):
        if "\u3400" <= word[0] <= "\u9fff" and len(word) > 1:
            result.update(word[i:i+2] for i in range(len(word)-1))
        else:
            result.add(word)
    return result


@dataclass(frozen=True)
class Passage:
    document: Document
    section: int
    heading: str
    text: str

    @cached_property
    def key(self):
        return hashlib.sha256(self.embedding_text.encode()).hexdigest()

    @property
    def embedding_text(self):
        return self.document.filename + "\n" + self.heading + "\n" + self.text


def passages(documents):
    for document in documents:
        for index, (title, body) in enumerate(document.sections):
            body = body.strip()
            start = 0
            while start < len(body):
                end = min(start + 1400, len(body))
                if end < len(body):
                    boundary = body.rfind("\n", start+900, end)
                    if boundary >= 0:
                        end = boundary+1
                yield Passage(document, index, title, body[start:end])
                if end == len(body):
                    break
                start = end - 100


def ranked_sections(query, chunks, vector_scores, limit):
    terms = _terms(query)
    if not terms:
        return []
    term_sets = [_terms(p.embedding_text) for p in chunks]
    frequency = Counter(t for ts in term_sets for t in (terms & ts))
    weights = {t: math.log1p((len(chunks)+1)/(1+frequency[t])) for t in terms}
    total = sum(weights.values())
    lowered = query.strip().casefold()
    by_section = {}
    for p, words in zip(chunks, term_sets, strict=True):
        hits = words & terms
        lexical = sum(weights[t] for t in hits) / total
        title_hits = _terms(p.heading + " " + p.document.filename) & terms
        lexical += 0.45 * sum(weights[t] for t in title_hits) / total
        if lowered in p.heading.casefold() or lowered in p.text.casefold():
            lexical += 0.35
        semantic = vector_scores.get(p.key, 0)
        if not hits and semantic < 0.48:
            continue
        score = lexical + max(0, semantic)*0.8
        key = (p.document.id, p.section)
        if key not in by_section or score > by_section[key][0]:
            by_section[key] = (score, p)
    ranked = sorted(by_section.values(), key=lambda item: (-item[0], item[1].document.filename, item[1].section))
    return [{"document_id": p.document.id, "filename": p.document.filename, "heading": p.heading,
             "section": p.section, "version": p.document.version, "excerpt": p.text,
             "url": p.document.link(p.section)} for _, p in ranked[:limit]]
