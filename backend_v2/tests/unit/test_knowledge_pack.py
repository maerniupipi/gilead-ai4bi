from pathlib import Path

from xiaoying_quick.modules.labs.knowledge_pack import (
    format_upstream_context,
    pack_from_documents,
    pack_loop_prompts,
)


def test_pack_only_includes_glossary_keys_in_query() -> None:
    packed = pack_loop_prompts(
        query="销量是多少",
        glossary={"销量": "sales_val", "安达唐": "brand"},
        unconfirmed_preferences=("金额",),
        confirmed={"达成": "金额"},
        kpi_formulas="Actual = sales",
        time_anchor="【时间基准】数据最新月份为 2026 年 7 月。",
    )
    assert "销量: sales_val" in packed["loop_prompt_1"]
    assert "安达唐" not in packed["loop_prompt_1"]
    assert packed["loop_prompt_4"].startswith("Actual")
    assert "时间基准" in packed["loop_prompt_3"]
    assert packed["loop_prompt_5"] == ""
    assert "金额" not in packed["loop_prompt_2"]


def test_pack_loop_prompts_puts_upstream_in_slot_5() -> None:
    packed = pack_loop_prompts(
        query="这些省份的增速",
        upstream_context="【上游已核验】\n上游SQL：SELECT province FROM t",
    )
    assert "上游已核验" in packed["loop_prompt_5"]
    assert "SELECT province FROM t" in packed["loop_prompt_5"]


def test_format_upstream_context_keeps_sql_when_rows_overflow() -> None:
    hop = {
        "question": "销量前50省份",
        "sql": "SELECT province FROM sales ORDER BY amt DESC LIMIT 50",
        "columns": ["province", "amt"],
        "rows": [[f"省{index}", index] for index in range(80)],
        "row_count": 80,
    }
    text = format_upstream_context(hop)
    assert "销量前50省份" in text
    assert "SELECT province FROM sales" in text
    assert "IN (上游SQL)" in text


def test_pack_always_emits_five_string_keys() -> None:
    packed = pack_loop_prompts(query="hello")
    assert list(packed) == [f"loop_prompt_{i}" for i in range(1, 6)]
    assert all(isinstance(value, str) for value in packed.values())


def test_pack_from_documents_fills_glossary_formula_and_time_anchor(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "业务知识.md").write_text(
        "## 业务术语\n\n| 标准术语 | 别名 |\n|---|---|\n"
        "| sales_qty | 销量、开票销量 |\n\n"
        "## KPI 指标\n\n| 指标 | 名称 | 公式 |\n|---|---|---|\n"
        "| sales_qty | 开票销量 | SUM(sales_qty) |\n",
        encoding="utf-8",
    )
    packed = pack_from_documents(
        knowledge_root=root,
        lab_id="actual",
        query="开票销量是多少",
        bindings={"该省": "浙江"},
        confirmed={"达成": "金额达成率"},
        time_anchor="【时间基准】数据最新月份为 2026 年 7 月。",
    )
    assert "销量" in packed["loop_prompt_1"]
    assert "该省=浙江" in packed["loop_prompt_2"]
    assert "达成=金额达成率" in packed["loop_prompt_2"]
    assert packed["loop_prompt_4"]
    assert "时间基准" in packed["loop_prompt_3"]
    assert packed["loop_prompt_5"] == ""
