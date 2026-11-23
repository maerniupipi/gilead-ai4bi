"""Re-seeding follows the file, including where the file no longer says anything.

The maintainer edits these documents in place and restarts the API. That only
works if a second import overwrites what the first one wrote: an early return on
the row's id left the previous text serving every recall, so a rule corrected in
the document went on being read in its broken form. A heading that was renamed or
deleted has the same problem from the other side — its id is gone, so nothing
touches the old row, and the superseded rule keeps competing for recall against
the rule that replaced it.
"""

from __future__ import annotations

from pathlib import Path

from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.repositories.knowledge import (
    SqlAlchemyKnowledgeRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.infrastructure.search.knowledge_seed import seed_published_knowledge

_FIRST = """\
# 实验室总索引

## 2. 判别流程（按序）
1. 含「内外部」→ 外部。

## 3. 关键词与 KPI 词表（路由用）
| 渠道 | 自营、京东 |
"""

_EDITED = """\
# 实验室总索引

## 2. 判别流程（按序）
1. 整句含「内外部」→ 所有意图一律外部。

## 3. 关键词与 KPI 词表（路由用）
| 渠道 | 自营、京东 |
"""

_RENAMED = """\
# 实验室总索引

## 2. 判别流程（按序）
1. 含「内外部」→ 外部。

## 3. 关键词与 KPI 词表
| 渠道 | 自营、京东 |
"""


def _root(tmp_path: Path, text: str) -> Path:
    directory = tmp_path / "knowledge" / "项目知识文档"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "实验室总索引.md").write_text(text, encoding="utf-8")
    return tmp_path / "knowledge"


def _factory():  # type: ignore[no-untyped-def]
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _seed(factory, root: Path) -> None:  # type: ignore[no-untyped-def]
    with session_scope(factory) as session:
        seed_published_knowledge(SqlAlchemyKnowledgeRepository(session), root)


def _published(factory) -> dict[str, str]:  # type: ignore[no-untyped-def]
    with session_scope(factory) as session:
        entries = SqlAlchemyKnowledgeRepository(session).list_published()
    return {entry.title: entry.content for entry in entries}


def test_an_edited_section_replaces_the_text_that_was_seeded_before(tmp_path: Path) -> None:
    factory = _factory()
    _seed(factory, _root(tmp_path, _FIRST))
    _seed(factory, _root(tmp_path, _EDITED))

    body = _published(factory)["实验室总索引.md · 2. 判别流程（按序）"]
    assert "整句含「内外部」→ 所有意图一律外部。" in body
    assert "1. 含「内外部」→ 外部。" not in body


def test_a_renamed_heading_leaves_no_second_copy_of_the_rule(tmp_path: Path) -> None:
    factory = _factory()
    _seed(factory, _root(tmp_path, _FIRST))
    _seed(factory, _root(tmp_path, _RENAMED))

    titles = set(_published(factory))
    assert "实验室总索引.md · 3. 关键词与 KPI 词表" in titles
    assert "实验室总索引.md · 3. 关键词与 KPI 词表（路由用）" not in titles


def test_seeding_the_same_file_twice_changes_nothing(tmp_path: Path) -> None:
    factory = _factory()
    root = _root(tmp_path, _FIRST)
    _seed(factory, root)
    _seed(factory, root)

    with session_scope(factory) as session:
        entries = SqlAlchemyKnowledgeRepository(session).list_published()
    assert [entry.version for entry in entries] == [1] * len(entries)
    assert len(entries) == 3


def test_a_document_never_retires_another_document(tmp_path: Path) -> None:
    directory = tmp_path / "knowledge" / "项目知识文档"
    directory.mkdir(parents=True)
    (directory / "实验室总索引.md").write_text(_FIRST, encoding="utf-8")
    (directory / "业务知识.md").write_text(
        "# 业务知识\n\n## 1. 产品别名\n可定 = 瑞舒伐他汀\n", encoding="utf-8"
    )
    root = tmp_path / "knowledge"

    factory = _factory()
    _seed(factory, root)
    (directory / "实验室总索引.md").write_text(_RENAMED, encoding="utf-8")
    _seed(factory, root)

    assert "业务知识.md · 1. 产品别名" in _published(factory)


def test_seed_uses_ascii_fallback_when_chinese_paths_are_missing(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    labs = root / "seed-files" / "labs"
    labs.mkdir(parents=True)
    (root / "seed-files" / "business.md").write_text(
        "# 业务知识\n\n## 1. 产品别名\n可定 = 瑞舒伐他汀\n", encoding="utf-8"
    )
    (root / "seed-files" / "lab-index.md").write_text(_FIRST, encoding="utf-8")
    (root / "seed-files" / "data-dictionary.md").write_text(
        "# 数据字典\n\n## sales_target_ai4bi\n字段说明\n", encoding="utf-8"
    )
    (labs / "ddi.md").write_text("# ddi\n\n## 1. 何时找我\n销量\n", encoding="utf-8")

    factory = _factory()
    _seed(factory, root)
    published = _published(factory)
    assert "业务知识.md · 1. 产品别名" in published
    assert "实验室总索引.md · 2. 判别流程（按序）" in published
    assert "labs/ddi.md · 1. 何时找我" in published


def test_seed_skips_missing_files_without_writing_rows(tmp_path: Path) -> None:
    factory = _factory()
    _seed(factory, tmp_path / "knowledge")
    assert _published(factory) == {}
