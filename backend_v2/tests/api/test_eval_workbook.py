from collections.abc import Callable

from fastapi.testclient import TestClient

from xiaoying_quick.infrastructure.eval_xlsx import (
    EvalRow,
    EvalSheet,
    EvalWorkbook,
    dump_xlsx,
    parse_xlsx,
)
from xiaoying_quick.modules.identity.contracts import UserRecord


def _xlsx() -> bytes:
    return dump_xlsx(
        EvalWorkbook(
            filename="工作簿1.xlsx",
            sheets=(
                EvalSheet(
                    name="思考模式",
                    headers=(
                        "问题分类",
                        "问题",
                        "澄清选项",
                        "最终sql",
                        "实验室选择",
                        "最终结果",
                        "持续时间",
                    ),
                    rows=(
                        EvalRow(
                            row_number=2,
                            values={
                                "问题分类": "长短词",
                                "问题": "安达唐今年销量是多少",
                                "最终sql": "SELECT 1\nSELECT 1",
                                "实验室选择": "实验室：actual",
                                "最终结果": "旧答案",
                            },
                        ),
                    ),
                ),
            ),
        )
    )


def test_eval_page_redirects_into_the_spa(client: TestClient) -> None:
    page = client.get("/eval.html", follow_redirects=False)
    assert page.status_code == 307
    assert page.headers["location"].endswith("/#/eval")
    alias = client.get("/eval", follow_redirects=False)
    assert alias.status_code == 307
    assert alias.headers["location"].endswith("/#/eval")


def test_parse_and_export_workbook(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("eval-user")
    headers = auth_headers("eval-user")

    parsed = client.post(
        "/api/v2/eval/workbooks/parse",
        files={
            "file": (
                "工作簿1.xlsx",
                _xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=headers,
    )
    assert parsed.status_code == 200, parsed.text
    body = parsed.json()
    assert body["sheets"][0]["question_count"] == 1
    values = body["sheets"][0]["rows"][0]["values"]
    assert values["问题"] == "安达唐今年销量是多少"
    assert "最终sql" not in values
    assert "实验室选择" not in values
    assert "最终结果" not in values

    body["sheets"][0]["rows"][0]["values"]["最终结果"] = "42"
    body["sheets"][0]["rows"][0]["values"]["持续时间"] = "8秒"
    exported = client.post(
        "/api/v2/eval/workbooks/export",
        json={"filename": "结果.xlsx", "sheets": body["sheets"]},
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    workbook = parse_xlsx(exported.content)
    assert workbook.sheets[0].questions()[0].values["最终结果"] == "42"
    assert workbook.sheets[0].questions()[0].values["持续时间"] == "8秒"


def test_eval_batch_persists_one_item_and_export_reads_from_db(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("eval-owner")
    headers = auth_headers("eval-owner")
    created = client.post(
        "/api/v2/eval/batches",
        json={"filename": "实验室评测.xlsx"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["id"]

    saved = client.put(
        f"/api/v2/eval/batches/{batch_id}/items",
        json={
            "sheet": "思考模式",
            "row": 2,
            "question": "安达唐今年销量是多少",
            "category": "长短词",
            "status": "done",
            "clarify": "问：口径？\n答：金额",
            "sql": "SELECT 1",
            "labs": "实验室：actual",
            "answer": "42",
            "duration": "8秒",
            "run_id": "run-1",
            "headers": ["问题分类", "问题"],
            "values": {"问题分类": "长短词"},
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    summary = saved.json()
    assert summary["answer_preview"] == "42"
    assert "sql" not in summary

    listed = client.get(f"/api/v2/eval/batches/{batch_id}/items", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["status"] == "done"
    assert "sql" not in listed.json()["items"][0]

    detail = client.get(
        f"/api/v2/eval/batches/{batch_id}/items/one",
        params={"sheet": "思考模式", "row": 2},
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["sql"] == "SELECT 1"
    assert detail.json()["answer"] == "42"

    exported = client.get(f"/api/v2/eval/batches/{batch_id}/export", headers=headers)
    assert exported.status_code == 200, exported.text
    workbook = parse_xlsx(exported.content)
    assert workbook.sheets[0].questions()[0].values["最终结果"] == "42"
    assert workbook.sheets[0].questions()[0].values["最终sql"] == "SELECT 1"


def test_parse_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v2/eval/workbooks/parse",
        files={
            "file": (
                "a.xlsx",
                _xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 401
