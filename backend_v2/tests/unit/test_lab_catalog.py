from pathlib import Path

import pytest

from xiaoying_quick.modules.knowledge.lab_catalog import (
    allowed_lab_ids,
    assert_labs_allowed,
    lab_ids_from_index,
    list_lab_documents,
    match_lab_document,
)


def test_lab_ids_parsed_from_index_table() -> None:
    text = """
| lab_id | 名称 |
|---|---|
| `actual` | Actual |
| `demand` | Demand |
"""
    assert lab_ids_from_index(text) == ("actual", "demand")


def test_allowed_labs_are_index_intersect_tokens() -> None:
    root = Path(__file__).resolve().parents[3] / "knowledge_gilead"
    allowed = allowed_lab_ids(root, {"actual": "t", "unknown": "t"})
    assert allowed is not None
    assert "actual" in allowed
    assert "unknown" not in allowed
    assert allowed <= {"actual"}


def test_missing_index_and_tokens_does_not_close_the_catalog() -> None:
    assert allowed_lab_ids(Path("/tmp/does-not-exist-lab-catalog"), None) is None


def test_lab_documents_match_markdown_title_and_lab_id(tmp_path: Path) -> None:
    labs = tmp_path / "labs"
    labs.mkdir()
    (labs / "外部市场-简单.md").write_text(
        "# 外部市场·简单 实验室\n\n> lab_id: `ext_simple` · 外部点值\n\n外部点值与变化量。\n",
        encoding="utf-8",
    )
    documents = list_lab_documents(tmp_path)
    assert len(documents) == 1
    assert documents[0].lab_id == "ext_simple"
    assert documents[0].name == "外部市场·简单"
    assert match_lab_document(tmp_path, "外部市场-简单") is not None
    assert match_lab_document(tmp_path, "ext_simple") is not None
    assert match_lab_document(tmp_path, "不存在") is None


def test_assert_labs_allowed_rejects_id_outside_intersection() -> None:
    allowed = frozenset({"actual"})
    assert_labs_allowed(("actual",), allowed)
    with pytest.raises(ValueError, match="intersection"):
        assert_labs_allowed(("ghost",), allowed)
