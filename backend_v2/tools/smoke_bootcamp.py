"""Verify the real Bootcamp demo labs and ReAct's cached evidence execution.

Run from backend_v2: .venv/bin/python tools/smoke_bootcamp.py --help
The script reads demo data and creates platform execution traces. It does not
seed labs, change platform configuration, or connect to ReAct's source database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xiaoying_quick.infrastructure.lab_http.bootcamp import (  # noqa: E402
    BootcampLabAdapter,
    BootcampLabConfig,
)
from xiaoying_quick.modules.labs import LabRequest  # noqa: E402

CASES = (
    ("sales", "DEMOSALES1", "2026年各区域销售额", "sales", ("region", "total_sales_amount"), 6),
    (
        "inventory",
        "DEMOSTOCK1",
        "按仓库汇总库存量",
        "inventory",
        ("warehouse", "total_stock_qty"),
        4,
    ),
    (
        "customers",
        "DEMOCUSTS1",
        "各城市客户数量",
        "customers",
        ("city", "total_customer_count"),
        12,
    ),
)


class SmokeCheckError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default=os.getenv(
            "BOOTCAMP_LAB_ENDPOINT", "http://127.0.0.1:8050/internal/lab/sql-evidence"
        ),
        help="Full Bootcamp SQL-evidence URL; defaults to the local service on port 8050.",
    )
    parser.add_argument(
        "--token",
        help="Internal service token; prefer BOOTCAMP_INTERNAL_TOKEN or INTERNAL_SERVICE_TOKEN.",
    )
    parser.add_argument(
        "--platform-root",
        type=Path,
        help="AI大集合 or new-chat directory; reads deploy/.env INTERNAL_SERVICE_TOKEN only.",
    )
    parser.add_argument("--output", type=Path, help="Save the redacted JSON report to this path.")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--space-id", type=int, default=1)
    return parser


def _platform_token(root: Path) -> str:
    root = root.expanduser().resolve()
    env_path = root / "deploy" / ".env"
    if not env_path.is_file():
        env_path = root / "new-chat" / "deploy" / ".env"
    if not env_path.is_file():
        raise SmokeCheckError("platform_env_file_not_found")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if separator and key.strip() == "INTERNAL_SERVICE_TOKEN":
            # Parse quotes and comments without sourcing or evaluating shell code.
            try:
                values = shlex.split(value, comments=True, posix=True)
            except ValueError:
                raise SmokeCheckError("platform_token_assignment_invalid") from None
            if len(values) == 1 and values[0]:
                return values[0]
            raise SmokeCheckError("platform_token_assignment_invalid")
    raise SmokeCheckError("platform_internal_token_not_configured")


def _resolve_token(args: argparse.Namespace) -> str:
    token = (
        args.token or os.getenv("BOOTCAMP_INTERNAL_TOKEN") or os.getenv("INTERNAL_SERVICE_TOKEN")
    )
    if not token and args.platform_root:
        token = _platform_token(args.platform_root)
    if not token:
        raise SmokeCheckError("set_BOOTCAMP_INTERNAL_TOKEN_or_use_platform_root")
    return token


def _safe_error(error: Exception) -> dict[str, object]:
    # Never stringify transport exceptions, response bodies, or configuration.
    result: dict[str, object] = {"type": type(error).__name__}
    if isinstance(error, SmokeCheckError):
        result["check"] = str(error)
    code = getattr(error, "code", None)
    if code is not None:
        result["code"] = getattr(code, "value", type(code).__name__)
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        result["http_status"] = status
    return result


def _check(condition: bool, name: str) -> None:
    if not condition:
        raise SmokeCheckError(name)


async def _run_case(args: argparse.Namespace, token: str, case: tuple) -> dict[str, object]:
    key, api_id, question, table, expected_columns, expected_rows = case
    started = time.monotonic()
    requests_sent = 0
    statuses: list[int] = []
    report: dict[str, object] = {
        "lab": key,
        "api_access_id": api_id,
        "question": question,
        "table": table,
    }

    async def on_request(_request: httpx.Request) -> None:
        nonlocal requests_sent
        requests_sent += 1

    async def on_response(response: httpx.Response) -> None:
        statuses.append(response.status_code)

    try:
        host = urlsplit(args.endpoint).hostname
        config = BootcampLabConfig(
            endpoint_url=args.endpoint,
            authorization=token,
            lab_ids={key: api_id},
            timeout_seconds=args.timeout,
            user_id=args.user_id,
            space_id=args.space_id,
            allow_insecure_http=host in {"localhost", "127.0.0.1", "::1"},
        )
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            event_hooks={"request": [on_request], "response": [on_response]},
        ) as client:
            async with BootcampLabAdapter(config, client=client) as adapter:
                candidates = await adapter.generate_sql(
                    LabRequest(atom_id=f"smoke-{key}", lab_id=key, query=question)
                )
                _check(len(candidates) == 1, "single_demo_candidate")
                candidate = candidates[0]
                requests_after_generate = requests_sent
                columns, rows, truncated, _duration_ms = adapter.execute(
                    candidate.sql, max_rows=100
                )
                repeated = adapter.execute(candidate.sql, max_rows=100)
                _check(tuple(columns) == expected_columns, "expected_demo_columns")
                _check(len(rows) == expected_rows, "expected_demo_row_count")
                _check(not truncated, "demo_result_not_truncated")
                _check(all(len(row) == len(columns) for row in rows), "rectangular_rows")
                _check(
                    all(isinstance(row[0], str) and row[0] for row in rows),
                    "nonempty_dimension_values",
                )
                _check(
                    all(
                        isinstance(row[1], (int, float))
                        and not isinstance(row[1], bool)
                        and math.isfinite(row[1])
                        and row[1] >= 0
                        for row in rows
                    ),
                    "numeric_aggregate_values",
                )
                _check(repeated[:3] == (columns, rows, truncated), "cache_result_stable")
                _check(requests_sent == requests_after_generate == 1, "cache_never_requeries")
                _check(statuses == [200], "platform_http_200")
                encoded_rows = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
                report.update(
                    {
                        "ok": True,
                        "http_status": statuses[0],
                        "trace_id": candidate.session_id,
                        "sql": candidate.sql,
                        "columns": list(columns),
                        "row_count": len(rows),
                        "aggregate_total": round(sum(row[1] for row in rows), 4),
                        "rows_sha256": hashlib.sha256(encoded_rows.encode()).hexdigest(),
                        "cache_verified": True,
                    }
                )
    except Exception as error:
        report.update({"ok": False, "error": _safe_error(error)})
    report["http_requests"] = requests_sent
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


async def _run(args: argparse.Namespace, token: str) -> dict[str, object]:
    # Keep one adapter per case, matching the runtime's per-run evidence lifetime.
    results = [await _run_case(args, token, case) for case in CASES]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": "real_bootcamp_platform_demo",
        "ok": all(result["ok"] for result in results),
        "source_rows": {"sales": 2160, "inventory": 48, "customers": 72},
        "checks": results,
    }


def main() -> int:
    args = _parser().parse_args()
    token = ""
    try:
        token = _resolve_token(args)
        report = asyncio.run(_run(args, token))
    except Exception as error:
        report = {"ok": False, "error": _safe_error(error)}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if token:
        encoded = encoded.replace(token, "[REDACTED]")
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
        except OSError:
            print('{"ok": false, "error": {"check": "report_write_failed"}}')
            return 1
    print(encoded)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
