from xiaoying_quick.infrastructure.source_db import parse_azai_query_payload


def test_parse_azai_end_event_rows() -> None:
    payload = {
        "end": True,
        "content": [
            {
                "type": "text",
                "text": {
                    "value": '{"data":[{"province_name":"江苏","sales_val":12.5}],'
                    '"code":200,"msg":"操作成功"}'
                },
            }
        ],
    }
    columns, rows = parse_azai_query_payload(payload)
    assert columns == ("province_name", "sales_val")
    assert rows == (("江苏", 12.5),)


def test_parse_azai_empty_data() -> None:
    payload = {"content": [{"text": {"value": '{"data":[],"code":200,"msg":"操作成功"}'}}]}
    assert parse_azai_query_payload(payload) == ((), ())
