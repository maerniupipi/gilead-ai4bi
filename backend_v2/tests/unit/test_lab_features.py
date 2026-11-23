"""Feature assembly: time anchors, per-lab knowledge blocks, remark."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from xiaoying_quick.modules.labs.lab_features import (
    DEFAULT_TRTY_CODE,
    build_call_features,
    build_static_features,
    sales_anchor,
    time_anchor_text,
)

_ACTUAL_DOC = """\
# Actual 实验室

> lab_id: `actual`

## 4. 支持的 KPI（仅此 12 个）

| # | KPI | 别名 | 计算逻辑 |
|---|---|---|---|
| 1 | Actual | 实际销售金额、销量 | 实际销售金额 |
| 6 | A/T% | 达成率、达成 | 实际销售金额 ÷ 销售指标 |

## 6. 常见歧义与澄清话术

- 「达成」默认金额 A/T%；数量达成需明确。
"""

_EXT_COMPLEX_DOC = """\
# 外部市场·复杂 实验室

> lab_id: `ext_complex`

## 3. 数据范围与维度

| 维度 | 取值 |
|---|---|
| 市场 | Severe Asthma Market 等 |

## 4. 指标与口径（标签2）

MS% = 产品销售额 ÷ 市场总额
"""


def _root(tmp_path: Path) -> Path:
    labs = tmp_path / "labs"
    labs.mkdir()
    (labs / "actual.md").write_text(_ACTUAL_DOC, encoding="utf-8")
    (labs / "外部市场-复杂.md").write_text(_EXT_COMPLEX_DOC, encoding="utf-8")
    return tmp_path


def test_sales_anchor_uses_configured_month() -> None:
    assert sales_anchor("2026-07") == (2026, 7)


def test_sales_anchor_defaults_to_previous_month() -> None:
    assert sales_anchor(None, today=date(2026, 8, 20)) == (2026, 7)
    # January rolls back to December of the previous year.
    assert sales_anchor(None, today=date(2026, 1, 15)) == (2025, 12)


def test_time_anchor_text_states_every_convention() -> None:
    text = time_anchor_text(2026, 7)
    assert "数据最新月默认为 2026 年 7 月" in text
    assert "以确认值为准" in text
    assert "2026 年 YTD 即 1 月到 7 月" in text
    assert "「去年」指 2025 年" in text
    assert "「上个月」指 6 月" in text


def test_actual_static_features_carry_kpis_and_ambiguity(tmp_path: Path) -> None:
    features = build_static_features(_root(tmp_path), "actual")
    assert features["kpis"] == "Actual、A/T%"
    assert "实际销售金额 ÷ 销售指标" in features["Actual_Prompt"]
    assert "「达成」默认金额 A/T%" in features["columns_value_knowledge"]


def test_ext_complex_static_features_carry_market_and_kpi(tmp_path: Path) -> None:
    features = build_static_features(_root(tmp_path), "ext_complex")
    assert "Severe Asthma Market" in features["market_danwei"]
    assert "MS%" in features["kpi_prompt"]
    assert "columns_value_knowledge" not in features


def test_build_call_features_fills_every_universal_key(tmp_path: Path) -> None:
    features = build_call_features(
        lab_id="actual",
        knowledge_root=_root(tmp_path),
        max_sales_month=None,
        remark="机构=中南大学湘雅医院",
        today=date(2026, 8, 20),
    )
    assert features["cur_sales_year"] == "2026"
    assert features["cur_sales_month"] == "7"
    assert features["max_sales_year"] == "2026"
    assert features["max_sales_month"] == "7"
    assert features["trty_code"] == DEFAULT_TRTY_CODE
    assert features["trty_code"] == "rsd_trty_code = RD_R40016"
    assert features["kcode"] == ""
    assert features["long_short_words"] == "None"
    assert features["remark"] == "机构=中南大学湘雅医院"
    assert features["kpis"] == "Actual、A/T%"


def test_build_call_features_allows_trty_code_override(tmp_path: Path) -> None:
    root = _root(tmp_path)
    features = build_call_features(
        lab_id="actual",
        knowledge_root=root,
        trty_code="  dsm_trty_code = DM_C44174  ",
    )
    assert features["trty_code"] == "dsm_trty_code = DM_C44174"

    blank = build_call_features(lab_id="actual", knowledge_root=root, trty_code="  ")
    assert blank["trty_code"] == ""


def test_build_call_features_skips_blank_remark(tmp_path: Path) -> None:
    features = build_call_features(lab_id="demand", knowledge_root=_root(tmp_path), remark="   ")
    assert "remark" not in features
