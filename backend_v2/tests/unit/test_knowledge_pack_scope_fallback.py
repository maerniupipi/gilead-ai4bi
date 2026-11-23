"""Glossary matching normalizes terms and falls back to the full table."""

from __future__ import annotations

from pathlib import Path

from xiaoying_quick.modules.labs.knowledge_pack import (
    _glossary_from_markdown,
    pack_from_documents,
    pack_loop_prompts,
)

_BUSINESS_MD = """\
# 业务知识

## 术语词表

| 术语 | 别名 |
| --- | --- |
| 达格列净 | 安达唐、Dagagliflozin |
| 依折麦布 | 益适纯 |

## KPI

| KPI | 名称 | 公式 |
| --- | --- | --- |
| EI | 增长指数 | 销售额 / 基期销售额 |
"""


def test_glossary_matches_normalized_alias() -> None:
    # Full-width letters and casing must not break alias matching.
    found = _glossary_from_markdown(_BUSINESS_MD, "ｄａｇａｇｌｉｆｌｏｚｉｎ 的销量")
    assert found == {"Dagagliflozin": "达格列净"}


def test_loop_prompt_falls_back_to_full_glossary_on_zero_hit() -> None:
    slots = pack_loop_prompts(
        query="某个词表里没有的说法",
        glossary={"达格列净": "安达唐", "依折麦布": "益适纯"},
    )
    assert "达格列净: 安达唐" in slots["loop_prompt_1"]
    assert "依折麦布: 益适纯" in slots["loop_prompt_1"]


def test_matched_glossary_stays_filtered() -> None:
    slots = pack_loop_prompts(
        query="安达唐的销量",
        glossary={"安达唐": "达格列净", "依折麦布": "益适纯"},
    )
    assert "安达唐: 达格列净" in slots["loop_prompt_1"]
    assert "依折麦布" not in slots["loop_prompt_1"]


def test_pack_from_documents_ships_full_glossary_when_no_alias_hits(
    tmp_path: Path,
) -> None:
    (tmp_path / "项目知识文档").mkdir()
    (tmp_path / "项目知识文档" / "业务知识.md").write_text(_BUSINESS_MD, encoding="utf-8")
    slots = pack_from_documents(knowledge_root=tmp_path, lab_id="unknown", query="完全无关的问法")
    assert "达格列净" in slots["loop_prompt_1"]
    assert "依折麦布" in slots["loop_prompt_1"]


def test_confirmed_scopes_land_in_slot_two() -> None:
    slots = pack_loop_prompts(
        query="安达唐的销量",
        confirmed={"已确认口径1": "只查重点民营机构"},
    )
    assert "已确认口径1=只查重点民营机构" in slots["loop_prompt_2"]
