from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from ...modules.knowledge.contracts import KnowledgeScope
from ..persistence.repositories.knowledge import SqlAlchemyKnowledgeRepository

_LOGGER = logging.getLogger(__name__)

# source path, stable identity path, scope, domain id
#
# The stable path intentionally keeps the previous value so moving the files into
# one maintainer-facing directory does not create duplicate seed entries.
# Sections that every question needs, whatever it asks about.
#
# Routing is not a retrieval problem. The priority table in §2 and the closed
# keyword lists in §3 decide where *any* question goes, so ranking them by word
# overlap against the question is backwards: a channel-only sales question shares
# no bigram with the row that makes that channel external, and so the one rule
# that would have routed it correctly is exactly the one that loses its budget
# slot. These titles are recalled at full length and at the top of the order; the
# similarity search still runs, for the material that genuinely is per-question.
PINNED_TITLE_PREFIXES: tuple[str, ...] = (
    "实验室总索引.md · 1.",
    "实验室总索引.md · 2.",
    "实验室总索引.md · 3.",
    "实验室总索引.md · 4.",
    "实验室总索引.md · 5.",
)


def is_pinned(title: str) -> bool:
    return title.startswith(PINNED_TITLE_PREFIXES)


SOURCE_MAP: tuple[tuple[str, str, KnowledgeScope, str | None], ...] = (
    ("项目知识文档/业务知识.md", "业务知识.md", KnowledgeScope.BUSINESS, None),
    (
        "项目知识文档/实验室总索引.md",
        "实验室总索引.md",
        KnowledgeScope.BUSINESS,
        None,
    ),
    ("项目知识文档/数据字典.md", "数据字典.md", KnowledgeScope.BUSINESS, None),
    # File name ddi.md; domain_id stays `actual` for Bootcamp credential slot.
    ("项目知识文档/labs/ddi.md", "labs/ddi.md", KnowledgeScope.DOMAIN, "actual"),
)

# Old AZ Actual lab doc — superseded by labs/ddi.md; retire leftover published rows.
RETIRED_STABLE_PREFIXES: tuple[str, ...] = (
    "labs/actual.md · ",
)

# ASCII copies written by package_sae.sh. macOS `zip` omits the UTF-8 flag, so
# Java unzip on SAE mangles 项目知识文档/*.md and the original paths vanish.
ASCII_FALLBACKS: dict[str, str] = {
    "项目知识文档/业务知识.md": "seed-files/business.md",
    "项目知识文档/实验室总索引.md": "seed-files/lab-index.md",
    "项目知识文档/数据字典.md": "seed-files/data-dictionary.md",
    "项目知识文档/labs/ddi.md": "seed-files/labs/ddi.md",
}


def _resolve_source(knowledge_root: Path, source_path: str) -> Path | None:
    candidates = (source_path, ASCII_FALLBACKS.get(source_path, ""))
    for relative in candidates:
        if not relative:
            continue
        path = knowledge_root / relative
        if path.is_file():
            return path
    return None


def seed_published_knowledge(
    repository: SqlAlchemyKnowledgeRepository, knowledge_root: Path
) -> int:
    for prefix in RETIRED_STABLE_PREFIXES:
        retired = repository.retire_imported(title_prefix=prefix, keep_ids=())
        if retired:
            _LOGGER.info("knowledge seed retired %s legacy rows (%s)", retired, prefix)
    imported = 0
    missing = 0
    for source_path, stable_path, scope, domain_id in SOURCE_MAP:
        path = _resolve_source(knowledge_root, source_path)
        if path is None:
            missing += 1
            _LOGGER.warning(
                "knowledge seed skipped missing file %s (root=%s)",
                source_path,
                knowledge_root,
            )
            continue
        text = path.read_text(encoding="utf-8")
        seeded: list[str] = []
        for heading, content in _sections(text):
            stable = hashlib.sha256(f"{stable_path}:{heading}".encode()).hexdigest()[:24]
            entry_id = f"seed_{stable}"
            repository.import_published(
                entry_id=entry_id,
                scope=scope,
                domain_id=domain_id,
                title=f"{stable_path} · {heading}",
                content=content,
                publisher_id="system-seed",
            )
            seeded.append(entry_id)
            imported += 1
        # The file is the whole truth about its own sections: a heading that was
        # renamed or deleted must stop being recalled, or the rule it used to
        # state keeps answering alongside the rule that replaced it.
        repository.retire_imported(title_prefix=f"{stable_path} · ", keep_ids=seeded)
    if imported == 0:
        _LOGGER.warning(
            "knowledge seed imported 0 sections from %s (%s mapped files missing)",
            knowledge_root,
            missing,
        )
    else:
        _LOGGER.info(
            "knowledge seed imported %s sections from %s",
            imported,
            knowledge_root,
        )
    return imported


def _sections(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if not matches:
        title = next(
            (line.lstrip("# ") for line in text.splitlines() if line.startswith("#")), "全文"
        )
        return [(title, text.strip())]
    result: list[tuple[str, str]] = []
    preface = text[: matches[0].start()].strip()
    if preface:
        result.append(("概览", preface))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result.append((match.group(1).strip(), text[match.start() : end].strip()))
    return result
