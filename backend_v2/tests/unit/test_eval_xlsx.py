from xiaoying_quick.infrastructure.eval_xlsx import (
    EvalRow,
    EvalSheet,
    EvalWorkbook,
    dump_xlsx,
    parse_xlsx,
    workbook_from_payload,
    workbook_to_payload,
    workbook_to_queue_payload,
)


def _book(*rows: dict[str, str], name: str = "思考模式") -> EvalWorkbook:
    headers = ("问题分类", "问题", "澄清选项", "最终sql", "实验室选择", "最终结果", "持续时间")
    return EvalWorkbook(
        filename="评测.xlsx",
        sheets=(
            EvalSheet(
                name=name,
                headers=headers,
                rows=tuple(
                    EvalRow(row_number=index + 2, values=dict(row))
                    for index, row in enumerate(rows)
                ),
            ),
        ),
    )


def test_round_trip_keeps_questions_and_result_columns() -> None:
    original = _book(
        {
            "问题分类": "长短词",
            "问题": "安达唐今年销量是多少",
            "澄清选项": "问：口径？\n答：金额（推荐）",
            "最终sql": "===== SQL 1（最终查询） =====\nSELECT 1",
            "实验室选择": "实验室：actual\nsession_id：lab-1",
            "最终结果": "42",
            "持续时间": "12秒",
        }
    )
    parsed = parse_xlsx(dump_xlsx(original), filename="评测.xlsx")
    assert parsed.sheets[0].name == "思考模式"
    row = parsed.sheets[0].questions()[0]
    assert row.values["问题"] == "安达唐今年销量是多少"
    assert "金额" in row.values["澄清选项"]
    assert "SELECT 1" in row.values["最终sql"]
    assert "lab-1" in row.values["实验室选择"]
    assert row.values["最终结果"] == "42"


def test_empty_category_is_filled_down_from_the_previous_row() -> None:
    original = _book(
        {"问题分类": "长短词", "问题": "第一题"},
        {"问题分类": "", "问题": "第二题"},
    )
    parsed = parse_xlsx(dump_xlsx(original))
    questions = parsed.sheets[0].questions()
    assert questions[0].values["问题分类"] == "长短词"
    assert questions[1].values["问题分类"] == "长短词"


def test_payload_round_trip_exports_filled_rows() -> None:
    workbook = workbook_from_payload(
        {
            "filename": "结果.xlsx",
            "sheets": [
                {
                    "name": "非思考模式",
                    "headers": ["问题分类", "问题", "最终结果"],
                    "rows": [
                        {
                            "row": 2,
                            "values": {
                                "问题分类": "排名问题",
                                "问题": "销量第一是谁",
                                "最终结果": "广东",
                            },
                        }
                    ],
                }
            ],
        }
    )
    payload = workbook_to_payload(workbook)
    assert payload["sheets"][0]["name"] == "非思考模式"
    assert payload["sheets"][0]["question_count"] == 1
    assert payload["sheets"][0]["rows"][0]["values"]["最终结果"] == "广东"
    parsed = parse_xlsx(dump_xlsx(workbook))
    assert parsed.sheets[0].questions()[0].values["问题"] == "销量第一是谁"


def test_queue_payload_drops_previous_sql_and_lab_results() -> None:
    original = _book(
        {
            "问题分类": "长短词",
            "问题": "安达唐今年销量是多少",
            "最终sql": "SELECT 1\nSELECT 1\nSELECT 1",
            "实验室选择": "实验室：actual\n实验室：actual",
            "最终结果": "42",
        }
    )
    payload = workbook_to_queue_payload(original)
    values = payload["sheets"][0]["rows"][0]["values"]
    assert values["问题"] == "安达唐今年销量是多少"
    assert values["问题分类"] == "长短词"
    assert "最终sql" not in values
    assert "实验室选择" not in values
    assert "最终结果" not in values
