from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from xiaoying_quick.modules.identity.contracts import Role, UserRecord
from xiaoying_quick.shared.compat import parse_iso_datetime


def test_linked_candidate_derives_source_question_from_owned_run(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("alice")
    headers = auth_headers("alice")
    question = "查安达唐 2025Q3 在 AIA NIAD 市场、PDOT 口径下的指标"
    accepted = client.post(
        "/api/v2/chat",
        headers=headers,
        json={"question": question},
    )
    assert accepted.status_code == 202, accepted.text

    proposed = client.post(
        "/api/v2/knowledge/candidates",
        headers=headers,
        json={
            "scope": "domain",
            "domain_id": "ext_simple",
            "title": "人工关联的域口径",
            "content": "这是一条等待审核的域口径。",
            "rationale": "关联已有运行以便审核来源。",
            "source_run_id": accepted.json()["run_id"],
            "source_question": "客户端伪造的问题不应被采信",
        },
    )

    assert proposed.status_code == 201, proposed.text
    payload = proposed.json()
    assert payload["source_question"] == question
    assert payload["source_question"] != "客户端伪造的问题不应被采信"
    assert payload["applicability"] == "domain:ext_simple"
    assert payload["clarification_question"] is None
    assert payload["clarification_answer"] is None
    assert payload["valid_from"] is None
    assert payload["valid_until"] is None


def test_review_queue_returns_current_logical_version_and_publication_carries_validity(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("admin", role=Role.ADMIN)
    seed_user("author")
    admin = auth_headers("admin")
    author = auth_headers("author")
    starts = datetime.now(timezone.utc) - timedelta(hours=1)
    ends = starts + timedelta(days=30)

    first = client.post(
        "/api/v2/knowledge/candidates",
        headers=author,
        json={
            "scope": "domain",
            "domain_id": "actual",
            "title": "Actual 月度口径",
            "content": "Actual 月度口径 v1",
            "rationale": "首版",
            "applicability": "domain:actual; grain:month",
        },
    )
    assert first.status_code == 201, first.text
    first_published = client.post(
        f"/api/v2/admin/knowledge/reviews/{first.json()['id']}/approve",
        headers=admin,
        json={},
    )
    assert first_published.status_code == 200, first_published.text

    second = client.post(
        "/api/v2/knowledge/candidates",
        headers=author,
        json={
            "scope": "domain",
            "domain_id": "ACTUAL",
            "title": "Ａｃｔｕａｌ   月度口径",
            "content": "Actual 月度口径 v2",
            "rationale": "补充有效期与适用粒度",
            "applicability": "domain:actual; grain:month; metric:sales_val",
            "valid_from": starts.isoformat(),
            "valid_until": ends.isoformat(),
        },
    )
    assert second.status_code == 201, second.text

    queue = client.get("/api/v2/admin/knowledge/reviews", headers=admin)
    assert queue.status_code == 200, queue.text
    review_item = next(item for item in queue.json() if item["id"] == second.json()["id"])
    assert [entry["id"] for entry in review_item["published_conflicts"]] == [
        first_published.json()["published"]["id"]
    ]
    assert review_item["published_conflicts"][0]["version"] == 1

    approved = client.post(
        f"/api/v2/admin/knowledge/reviews/{second.json()['id']}/approve",
        headers=admin,
        json={"comment": "有效期与适用范围已核验"},
    )
    assert approved.status_code == 200, approved.text
    published = approved.json()["published"]
    assert published["version"] == 2
    assert published["applicability"] == ("domain:actual; grain:month; metric:sales_val")
    assert parse_iso_datetime(published["valid_from"]) == starts
    assert parse_iso_datetime(published["valid_until"]) == ends

    invalid = client.post(
        "/api/v2/knowledge/candidates",
        headers=author,
        json={
            "scope": "business",
            "title": "无效时间窗",
            "content": "结束时间不得早于开始时间。",
            "rationale": "校验 API",
            "valid_from": ends.isoformat(),
            "valid_until": starts.isoformat(),
        },
    )
    assert invalid.status_code == 422
