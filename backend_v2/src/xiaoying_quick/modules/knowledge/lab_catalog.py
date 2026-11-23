"""Lab ids allowed for a turn: index document intersect configured tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_LAB_CELL = re.compile(r"`([A-Za-z0-9][A-Za-z0-9_-]{0,127})`")
_LAB_ID_LINE = re.compile(r"lab_id:\s*`([A-Za-z0-9][A-Za-z0-9_-]{0,127})`")
_HEADING = re.compile(r"^#\s+(.+)$")


@dataclass(frozen=True)
class LabDocument:
    lab_id: str
    name: str
    path: str
    blurb: str


def lab_ids_from_index(index_text: str) -> tuple[str, ...]:
    ids: list[str] = []
    in_table = False
    for raw in index_text.splitlines():
        line = raw.strip()
        if line.startswith("|") and "lab_id" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and set(line.replace("|", "").strip()) <= {"-", ":"}:
            continue
        if in_table and line.startswith("|"):
            match = _LAB_CELL.search(line)
            if match:
                ids.append(match.group(1))
            continue
        if in_table and line and not line.startswith("|"):
            break
    return tuple(dict.fromkeys(ids))


def load_index_text(knowledge_root: Path) -> str:
    for path in sorted(knowledge_root.rglob("*.md")):
        if path.name == "实验室总索引.md":
            return path.read_text(encoding="utf-8")
    return ""


def list_lab_documents(knowledge_root: Path) -> tuple[LabDocument, ...]:
    if not knowledge_root.exists():
        return ()
    index_meta = _index_lab_meta(load_index_text(knowledge_root))
    found: dict[str, LabDocument] = {}
    for path in sorted(knowledge_root.rglob("labs/*.md")):
        text = path.read_text(encoding="utf-8")
        match = _LAB_ID_LINE.search(text)
        lab_id = match.group(1) if match else path.stem
        heading = ""
        for line in text.splitlines():
            heading_match = _HEADING.match(line.strip())
            if heading_match:
                heading = heading_match.group(1).strip()
                break
        name = re.sub(r"实验室$", "", heading).strip() or index_meta.get(lab_id, ("", ""))[0] or path.stem
        blurb = index_meta.get(lab_id, ("", ""))[1] or _first_blurb(text)
        relative = str(path.relative_to(knowledge_root)).replace("\\", "/")
        found[lab_id] = LabDocument(lab_id=lab_id, name=name, path=relative, blurb=blurb)
    return tuple(found.values())


def match_lab_document(knowledge_root: Path, name: str) -> LabDocument | None:
    needle = _norm_lab_name(name)
    if not needle:
        return None
    for document in list_lab_documents(knowledge_root):
        stem = Path(document.path).stem
        aliases = {_norm_lab_name(document.lab_id), _norm_lab_name(document.name), _norm_lab_name(stem)}
        if needle in aliases:
            return document
    return None


def allowed_lab_ids(
    knowledge_root: Path, configured_tokens: dict[str, str] | None
) -> frozenset[str] | None:
    listed = set(lab_ids_from_index(load_index_text(knowledge_root)))
    listed.update(document.lab_id for document in list_lab_documents(knowledge_root))
    tokens = set((configured_tokens or {}).keys())
    if listed and tokens:
        return frozenset(listed & tokens)
    if listed:
        return frozenset(listed)
    if tokens:
        return frozenset(tokens)
    return None


def _index_lab_meta(index_text: str) -> dict[str, tuple[str, str]]:
    meta: dict[str, tuple[str, str]] = {}
    in_table = False
    for raw in index_text.splitlines():
        line = raw.strip()
        if line.startswith("|") and "lab_id" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and set(line.replace("|", "").strip()) <= {"-", ":"}:
            continue
        if in_table and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            match = _LAB_CELL.search(cells[0] if cells else "")
            if match:
                title = cells[1] if len(cells) > 1 else ""
                blurb = cells[2] if len(cells) > 2 else ""
                meta[match.group(1)] = (title, blurb)
            continue
        if in_table and line and not line.startswith("|"):
            break
    return meta


def _first_blurb(markdown: str) -> str:
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(">") or line.startswith("|"):
            continue
        return re.sub(r"\*\*", "", line)[:80]
    return ""


def _norm_lab_name(value: str) -> str:
    text = value.strip().casefold().replace("·", "-").replace("—", "-").replace(" ", "")
    if text.endswith("实验室"):
        text = text[: -3]
    return text


def assert_labs_allowed(lab_ids: tuple[str, ...], allowed: frozenset[str]) -> None:
    unknown = [item for item in lab_ids if item not in allowed]
    if unknown:
        raise ValueError(f"lab_ids not in index and token intersection: {unknown}")
