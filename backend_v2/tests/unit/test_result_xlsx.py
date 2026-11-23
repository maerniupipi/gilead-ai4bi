from decimal import Decimal

from xiaoying_quick.infrastructure.result_xlsx import (
    AZ_NAVY,
    AZ_PLUM,
    dump_result_xlsx,
    parse_result_xlsx_meta,
)


def test_result_xlsx_uses_az_theme_merged_banner_and_all_rows() -> None:
    rows = [
        ["Vacant", "成都市", 24_409_575],
        ["万明飞", "济南市", Decimal("31011425")],
        ["于桐", "北京市", 31_050_675.5],
    ]
    payload = dump_result_xlsx(
        title="泰瑞沙 2025 YTD 各地区经理 × 各城市 Actual 销售金额",
        summary="Actual 销售金额（元），2025 年全年",
        columns=["地区经理", "城市", "Actual 销售金额"],
        rows=rows,
    )
    meta = parse_result_xlsx_meta(payload)
    assert meta["merge"] == "A1:C1"
    assert "泰瑞沙 2025 YTD" in meta["banner"]
    assert "Actual 销售金额" in meta["banner"]
    assert "完整结果共 3 行" in meta["banner"]
    assert meta["headers"] == ["地区经理", "城市", "Actual 销售金额"]
    assert meta["row_count"] == 3
    assert meta["row1_cells"] == 1
    assert meta["merge_after_filter"] is True
    assert meta["has_plum"] is True
    assert meta["has_navy"] is True
    assert AZ_PLUM.startswith("FF8A")
    assert AZ_NAVY.startswith("FF17")
    assert meta["frozen"] is True


def test_result_xlsx_writes_every_row_past_the_chat_preview_cap() -> None:
    rows = [[f"经理{index}", f"城市{index}", index] for index in range(462)]
    payload = dump_result_xlsx(
        title="完整结果",
        summary="共 462 行",
        columns=["地区经理", "城市", "金额"],
        rows=rows,
    )
    meta = parse_result_xlsx_meta(payload)
    assert meta["row_count"] == 462
    assert meta["merge"] == "A1:C1"
    assert meta["row1_cells"] == 1
    assert meta["merge_after_filter"] is True
    assert "完整结果共 462 行" not in meta["banner"]
    assert "共 462 行" in meta["banner"]


def test_multidimensional_report_export_preserves_rows_past_2000() -> None:
    rows = [[f"组合{index}", index] for index in range(2500)]
    payload = dump_result_xlsx(
        title="多维商业报表", summary="完整结果", columns=["维度组合", "金额"], rows=rows
    )
    assert parse_result_xlsx_meta(payload)["row_count"] == 2500
