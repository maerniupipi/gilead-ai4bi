"""Real POC chat smoke test; credentials are read locally and never printed."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
QUESTION = "2026年8月各大区的销量和人民币销售额是多少？请按销量降序展示，数据标注为模拟数据。"


def verify(run: dict, events: list[dict]) -> dict:
    queries = [
        event["payload"] for event in events
        if event["type"] == "tool.result" and event["payload"].get("name") == "query_db"
        and event["payload"].get("ok") is True
    ]
    generations = [
        event["payload"] for event in events
        if event["type"] == "tool.result"
        and event["payload"].get("name") in {"ask_lab", "generate_sql"}
        and event["payload"].get("ok") is True
    ]
    answers = [
        event["payload"]["answer"] for event in events
        if event["type"] == "agent.done" and not event["payload"].get("parent_call_id")
    ]
    if run["status"] != "completed" or not queries or not generations or not answers:
        raise AssertionError("未完成实验室生成、证据查询与最终回答的完整链路")
    preview = queries[-1]["preview"]
    assert preview["lab_provider"] == "bootcamp" and preview["mock_enabled"] is False
    assert preview["row_count"] == 6 and preview["truncated"] is False
    columns, rows = preview["columns"], preview["rows"]
    quantity = sum(Decimal(str(row[columns.index("sales_qty")])) for row in rows)
    amount = sum(Decimal(str(row[columns.index("sales_cny")])) for row in rows)
    report_manifest = ROOT / "deploy/gilead_poc/report-sample-manifest.json"
    golden_path = report_manifest if report_manifest.exists() else ROOT / "deploy/gilead_poc/seed-manifest.json"
    golden = json.loads(golden_path.read_text())
    case = next(case for case in golden["golden_cases"] if case["name"] == "month_yoy")
    totals = case["current_totals"]
    assert quantity == Decimal(totals[0]) and amount == Decimal(totals[1])
    regions = {row[columns.index("region")] for row in rows}
    assert regions == {"华南", "华东", "华中", "西南", "西北", "华北"}
    answer = answers[-1]
    assert "模拟数据" in answer and all(region in answer for region in regions)
    trace_id = next((
        payload.get("preview", {}).get("lab_session_id") for payload in generations
        if payload.get("preview", {}).get("lab_session_id")
    ), None)
    return {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed", "synthetic": True,
        "run_id": run["id"], "session_id": run["session_id"], "question": run["question"],
        "run_status": run["status"], "lab_provider": "bootcamp", "mock_enabled": False,
        "project_id": 29, "knowledge_base_id": 45, "data_source_id": 18,
        "lab_trace_id": trace_id, "sql": preview["sql"],
        "columns": columns, "rows": rows, "row_count": len(rows),
        "total_quantity": str(quantity), "total_cny": str(amount),
        "golden_totals_match": True, "answer": answer,
        "event_count": len(events),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18001")
    parser.add_argument("--run-id", help="验证已有运行，省去再次模型调用")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--report", type=Path,
                        default=ROOT / "deploy/gilead_poc/simple-flow-verification.json")
    args = parser.parse_args()
    os.chdir(ROOT / "backend_v2")
    from xiaoying_quick.bootstrap.settings import Settings

    settings = Settings()
    assert settings.bootstrap_admin_username and settings.bootstrap_admin_password
    with httpx.Client(base_url=args.base_url, timeout=45, trust_env=False) as client:
        def request(method: str, path: str, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
            return response.json()

        token = request("POST", "/api/v2/auth/token", json={
            "username": settings.bootstrap_admin_username,
            "password": settings.bootstrap_admin_password.get_secret_value(),
        })
        client.headers["Authorization"] = "Bearer " + token["access_token"]
        run_id = args.run_id
        if not run_id:
            accepted = request("POST", "/api/v2/chat", json={
                "question": QUESTION, "use_memory": False,
            })
            run_id = accepted["run_id"]
        print(f"验证运行 {run_id}", flush=True)
        events: list[dict] = []
        cursor = 0
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            page = request("GET", f"/api/v2/runs/{run_id}/events?after={cursor}&limit=1000")
            events.extend(page["items"])
            cursor = page["next_cursor"]
            statuses = [e["payload"].get("to") for e in events if e["type"] == "run.status_changed"]
            terminal = {"completed", "failed", "cancelled", "waiting_clarification"}
            if statuses and statuses[-1] in terminal:
                run = request("GET", f"/api/v2/runs/{run_id}")
                report = verify(run, events)
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                print(f"通过：6个大区，销量 {report['total_quantity']}，"
                      f"人民币 {report['total_cny']} 元。")
                print(f"报告：{args.report}")
                return
            if not page["has_more"]:
                time.sleep(3)
        raise SystemExit(f"业务验证超时，运行 {run_id} 的事件仍保留在控制库中。")


if __name__ == "__main__":
    main()
