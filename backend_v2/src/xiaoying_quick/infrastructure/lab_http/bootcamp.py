"""Bootcamp lab-service SQL-evidence transport, projected to SQL candidates only.

The platform endpoint executes its own lab pipeline. Its returned data, prose,
steps and errors are not facts. SQL execution evidence is exposed only through
execute(), for an exact previously generated SQL, inside a per-run adapter.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from xiaoying_quick.modules.labs import (
    CandidateSQL,
    LabContractError,
    LabRequest,
)

from .adapter import HttpLabAdapter, _content_length, _project_features, _safe_close
from .errors import LabHttpError, LabHttpErrorCode


@dataclass(frozen=True)
class BootcampLabConfig:
    endpoint_url: str
    authorization: str = field(repr=False)
    lab_ids: Mapping[str, str]
    timeout_seconds: float = 120.0
    user_id: int = 1
    space_id: int = 1
    allow_insecure_http: bool = False
    max_response_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        endpoint = self.endpoint_url.strip().rstrip("/")
        try:
            url = urlsplit(endpoint)
            hostname = url.hostname
            _ = url.port
        except ValueError:
            raise ValueError("Bootcamp 服务地址无效") from None
        if url.scheme not in {"http", "https"} or not hostname:
            raise ValueError("Bootcamp 服务地址必须为完整 HTTP(S) 地址")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Bootcamp 服务地址不能包含密钥、查询参数或片段")
        if url.scheme == "http" and not self.allow_insecure_http:
            raise ValueError("Bootcamp 服务地址必须使用 HTTPS")
        native = url.path.endswith("/api/autobi/gateway/v2/lab")
        if not (url.path.endswith("/internal/lab/sql-evidence") or native):
            raise ValueError("实验中心地址必须为 SQL evidence 接口或 /api/autobi/gateway/v2/lab")
        token = self.authorization
        if native and token.lower().startswith("bearer "):
            token = token[7:]
        if (
            (not token and not native)
            or (bool(self.authorization) and not token)
            or token != token.strip()
            or not all(0x21 <= ord(c) <= 0x7E for c in token)
        ):
            raise ValueError("请填写有效的 Bootcamp 内部访问密钥")
        object.__setattr__(self, "authorization", token)
        if not self.lab_ids or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            or not value.strip()
            or len(value) > 128
            or any(ord(c) < 0x21 for c in value)
            for key, value in self.lab_ids.items()
        ):
            raise ValueError("请配置 Bootcamp 实验室 API 调用 ID")
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 600
        ):
            raise ValueError("请求超时必须在 1–600 秒之间")
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v < 1
            for v in (self.user_id, self.space_id)
        ):
            raise ValueError("用户 ID 和空间 ID 必须为正整数")
        if isinstance(self.max_response_bytes, bool) or self.max_response_bytes <= 0:
            raise ValueError("响应大小上限必须为正整数")
        object.__setattr__(self, "endpoint_url", endpoint)
        object.__setattr__(self, "lab_ids", MappingProxyType(dict(self.lab_ids)))


class BootcampLabAdapter(HttpLabAdapter):
    """Reuse sanitized transport errors; keep the original Bailian adapter intact."""

    supports_controlled_prompt = False

    def __init__(
        self, config: BootcampLabConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        # HttpLabAdapter's request generation is overridden; lifecycle, extraction
        # and sanitized error classification are deliberately shared.
        super().__init__(config, client=client)  # type: ignore[arg-type]
        self._bootcamp_config = config
        self._evidence: dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...], bool]] = {}
        self._evidence_sources: dict[str, set[str]] = {}

    async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]:
        if not self._owns_client:
            return await self._generate_sql(request, self._client)
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            return await self._generate_sql(request, client)

    async def _generate_sql(
        self, request: LabRequest, client: httpx.AsyncClient
    ) -> tuple[CandidateSQL, ...]:
        if self._bootcamp_config.endpoint_url.endswith("/api/autobi/gateway/v2/lab"):
            return await self._generate_native(request, client)
        config = self._bootcamp_config
        request_id = self._new_request_id()

        def failure(
            code: LabHttpErrorCode, *, retryable: bool = False, status_code: int | None = None
        ) -> LabHttpError:
            return self._failure(
                code,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=retryable,
                status_code=status_code,
            )

        if self._closed:
            raise failure(LabHttpErrorCode.CLOSED)
        api_id = config.lab_ids.get(request.lab_id)
        if not api_id:
            raise failure(LabHttpErrorCode.INVALID_REQUEST)
        try:
            outbound = client.build_request(
                "POST",
                config.endpoint_url,
                headers={
                    "Accept": "application/json",
                    "X-Internal-Token": config.authorization,
                    "X-User-Id": str(config.user_id),
                    "X-Space-Id": str(config.space_id),
                    "X-Request-ID": request_id,
                },
                json={
                    "content": request.query,
                    "id": api_id,
                    "features": _project_features(request.session_params),
                },
                timeout=config.timeout_seconds,
            )
        except (ValueError, TypeError, httpx.HTTPError):
            raise failure(LabHttpErrorCode.INVALID_REQUEST) from None
        try:
            response = await client.send(outbound, stream=True, follow_redirects=False)
        except httpx.TimeoutException:
            raise failure(LabHttpErrorCode.TIMEOUT, retryable=True) from None
        except Exception:
            raise failure(LabHttpErrorCode.NETWORK_ERROR, retryable=True) from None
        body = bytearray()
        try:
            status_error = self._classify_status(response.status_code)
            if status_error:
                raise failure(
                    status_error[0], retryable=status_error[1], status_code=response.status_code
                )
            length = _content_length(response)
            if length is not None and length > config.max_response_bytes:
                raise failure(LabHttpErrorCode.RESPONSE_TOO_LARGE)
            try:
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > config.max_response_bytes:
                        raise failure(LabHttpErrorCode.RESPONSE_TOO_LARGE)
                    body.extend(chunk)
            except httpx.TimeoutException:
                raise failure(LabHttpErrorCode.TIMEOUT, retryable=True) from None
            except httpx.HTTPError:
                raise failure(LabHttpErrorCode.NETWORK_ERROR, retryable=True) from None
        finally:
            await _safe_close(response)
        try:
            raw = json.loads(body)
        except (ValueError, UnicodeError):
            raise failure(LabHttpErrorCode.INVALID_JSON) from None
        if not isinstance(raw, Mapping) or raw.get("error"):
            raise failure(LabHttpErrorCode.INVALID_RESPONSE)
        sqls = raw.get("sqls")
        citations: list[dict[str, str]] = []
        if isinstance(sqls, list):
            for item in sqls:
                if isinstance(item, Mapping) and isinstance(item.get("sql"), str):
                    citations.append({"query": request.query, "sql": item["sql"]})
        if not citations and isinstance(raw.get("sql"), str):
            citations.append({"query": request.query, "sql": raw["sql"]})
        projected = {"sql_citations": citations, "lab_session_id": raw.get("trace_id", "")}
        try:
            candidates = self._extractor.extract(
                projected, atom_id=request.atom_id, lab_id=request.lab_id
            )
            evidence = _parse_evidence(raw, candidates)
        except (LabContractError, ValueError, TypeError):
            raise failure(LabHttpErrorCode.INVALID_RESPONSE) from None
        for sql, result in evidence.items():
            sources = self._evidence_sources.setdefault(sql, set())
            sources.add(request.lab_id)
            if len(sources) > 1:
                self._evidence.pop(sql, None)
            else:
                self._evidence[sql] = result
        return candidates

    async def _generate_native(
        self, request: LabRequest, client: httpx.AsyncClient
    ) -> tuple[CandidateSQL, ...]:
        """Use J&J's native SSE and its matching persisted step-16 execution.

        The native stream contains prose, not a result grid. Only the executed
        SQL plus rows from this stream's exact trace may become query evidence.
        """
        config = self._bootcamp_config
        request_id = self._new_request_id()
        api_id = config.lab_ids.get(request.lab_id)
        headers = {
            "X-User-Id": str(config.user_id),
            "X-Space-Id": str(config.space_id),
            "X-Request-ID": request_id,
        }
        if config.authorization:
            headers["Authorization"] = (
                config.authorization
                if config.authorization.lower().startswith("bearer ")
                else "Bearer " + config.authorization
            )

        def fail(code=LabHttpErrorCode.INVALID_RESPONSE, *, retryable=False):
            return self._failure(
                code, request_id=request_id, lab_id=request.lab_id, retryable=retryable
            )

        async def read(method, url, **kwargs):
            body = bytearray()
            async with client.stream(
                method,
                url,
                headers=headers,
                timeout=config.timeout_seconds,
                follow_redirects=False,
                **kwargs,
            ) as response:
                status = self._classify_status(response.status_code)
                if status:
                    raise fail(status[0], retryable=status[1])
                length = _content_length(response)
                if length is not None and length > config.max_response_bytes:
                    raise fail(LabHttpErrorCode.RESPONSE_TOO_LARGE)
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > config.max_response_bytes:
                        raise fail(LabHttpErrorCode.RESPONSE_TOO_LARGE)
            return bytes(body)

        if self._closed or not api_id:
            raise fail(
                LabHttpErrorCode.CLOSED if self._closed else LabHttpErrorCode.INVALID_REQUEST
            )
        try:
            stream = await read(
                "POST",
                config.endpoint_url,
                json={
                    "content": request.query,
                    "id": api_id,
                    "features": _project_features(request.session_params),
                },
            )
            from xiaoying_quick.infrastructure.source_db.azai_runner import _parse_sse

            events = _parse_sse(stream.decode("utf-8"))
            if any(event.get("type") == "error" for event in events):
                raise ValueError("platform run failed")
            ids = {
                str(event["trace_id"])
                for event in events
                if event.get("type") == "trace_id" and event.get("trace_id")
            }
            if len(ids) != 1 or not any(event.get("type") == "done" for event in events):
                raise ValueError("incomplete or ambiguous trace")
            trace_id = ids.pop()
            UUID(trace_id)
            base = config.endpoint_url.removesuffix("/gateway/v2/lab")
            trace = json.loads(await read("GET", base + "/lab/traces/" + trace_id))
            if isinstance(trace, dict) and isinstance(trace.get("data"), dict):
                trace = trace["data"]
            if trace.get("trace_id") != trace_id or trace.get("user_message") != request.query:
                raise ValueError("trace does not match this request")
            steps = [step for step in trace.get("steps", []) if step.get("step_id") == 16]
            if len(steps) != 1 or steps[0].get("status") != "done":
                raise ValueError("missing successful query step")
            step = steps[0]
            executed = (step.get("request") or {}).get("sql")
            result = step.get("response") or {}
            if (
                not isinstance(executed, str)
                or not executed.strip()
                or step.get("error")
                or result.get("error")
                or result.get("skipped")
            ):
                raise ValueError("query was not executed successfully")
            candidates = self._extractor.extract(
                {
                    "sql_citations": [{"query": request.query, "sql": executed}],
                    "lab_session_id": trace_id,
                },
                atom_id=request.atom_id,
                lab_id=request.lab_id,
            )
            evidence = _parse_evidence({"evidence": [{**result, "sql": executed}]}, candidates)
        except LabHttpError:
            raise
        except httpx.TimeoutException:
            raise fail(LabHttpErrorCode.TIMEOUT, retryable=True) from None
        except httpx.HTTPError:
            raise fail(LabHttpErrorCode.NETWORK_ERROR, retryable=True) from None
        except (ValueError, TypeError, KeyError, AttributeError, LabContractError):
            raise fail() from None
        for statement, result in evidence.items():
            sources = self._evidence_sources.setdefault(statement, set())
            sources.add(request.lab_id)
            if len(sources) > 1:
                self._evidence.pop(statement, None)
            else:
                self._evidence[statement] = result
        return candidates

    def execute(
        self, sql: str, max_rows: int
    ) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...], bool, int]:
        """Expose matching platform SQL evidence; the final integer is duration_ms."""
        from xiaoying_quick.infrastructure.source_db.local_catalog import LocalSourceError

        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
            raise LocalSourceError("查询行数上限必须为正整数")
        key = _sql_key(sql)
        if len(self._evidence_sources.get(key, ())) > 1:
            raise LocalSourceError("多个实验室返回了相同 SQL，结果来源不明确。请新建独立提问查询。")
        result = self._evidence.get(key)
        if result is None:
            raise LocalSourceError("未找到这条 SQL 的平台执行证据，请重新调用实验室生成 SQL。")
        columns, rows, truncated = result
        return columns, rows[:max_rows], truncated or len(rows) > max_rows, 0

    def dump_evidence(self) -> dict[str, dict[str, Any]]:
        """JSON-safe run artifact; includes provenance and ambiguous SQL markers."""
        dumped = {}
        for sql, sources in self._evidence_sources.items():
            ambiguous = len(sources) > 1
            columns, rows, truncated = self._evidence.get(sql, ((), (), False))
            dumped[sql] = {
                "lab_ids": sorted(sources),
                "ambiguous": ambiguous,
                "columns": list(columns),
                "rows": [list(row) for row in rows],
                "truncated": truncated,
            }
        return dumped

    def restore_evidence(self, payload: object) -> None:
        """Validate an artifact before restoring it into this run's isolated cache."""
        if not isinstance(payload, dict):
            raise ValueError("Invalid laboratory evidence artifact")
        candidates: list[CandidateSQL] = []
        evidence: list[dict[str, Any]] = []
        sources_by_sql: dict[str, set[str]] = {}
        expected_fields = {"lab_ids", "ambiguous", "columns", "rows", "truncated"}
        for sql, item in payload.items():
            if (
                not isinstance(sql, str)
                or not sql
                or _sql_key(sql) != sql
                or not isinstance(item, dict)
                or set(item) != expected_fields
            ):
                raise ValueError("Invalid laboratory evidence artifact")
            lab_ids = item["lab_ids"]
            if (
                not isinstance(lab_ids, list)
                or not lab_ids
                or any(
                    not isinstance(lab_id, str) or lab_id not in self._bootcamp_config.lab_ids
                    for lab_id in lab_ids
                )
                or len(set(lab_ids)) != len(lab_ids)
            ):
                raise ValueError("Invalid laboratory evidence provenance")
            ambiguous = len(lab_ids) > 1
            if not isinstance(item["ambiguous"], bool) or item["ambiguous"] != ambiguous:
                raise ValueError("Invalid laboratory evidence provenance")
            sources_by_sql[sql] = set(lab_ids)
            if ambiguous:
                if item["columns"] != [] or item["rows"] != [] or item["truncated"] is not False:
                    raise ValueError("Invalid ambiguous laboratory evidence")
                continue
            candidates.append(
                CandidateSQL(
                    atom_id="restored",
                    lab_id=lab_ids[0],
                    query="restored",
                    sql=sql,
                    candidate_no=len(candidates),
                )
            )
            evidence.append(
                {
                    "sql": sql,
                    "columns": item["columns"],
                    "rows": item["rows"],
                    "truncated": item["truncated"],
                }
            )
        parsed = _parse_evidence({"evidence": evidence}, tuple(candidates))
        for sql, sources in sources_by_sql.items():
            combined = self._evidence_sources.setdefault(sql, set())
            combined.update(sources)
            if len(combined) > 1:
                self._evidence.pop(sql, None)
            elif sql in parsed:
                self._evidence[sql] = parsed[sql]


def _sql_key(sql: str) -> str:
    """Normalize SQL for evidence lookup (trim, drop trailing ';', collapse space)."""

    import re

    cleaned = sql.strip().removesuffix(";").strip()
    return re.sub(r"\s+", " ", cleaned)


def _parse_evidence(
    raw: Mapping[str, Any], candidates: tuple[CandidateSQL, ...]
) -> dict[str, tuple[tuple[str, ...], tuple[tuple[Any, ...], ...], bool]]:
    evidence = raw.get("evidence")
    if evidence is None and isinstance(raw.get("sql_data"), Mapping):
        evidence = [{**raw["sql_data"], "sql": raw.get("sql")}]
    if not isinstance(evidence, list):
        raise ValueError("missing execution evidence")
    expected = {_sql_key(candidate.sql) for candidate in candidates}
    projected = {}
    for item in evidence:
        if not isinstance(item, Mapping) or not isinstance(item.get("sql"), str):
            raise ValueError("invalid evidence")
        key = _sql_key(item["sql"])
        if key not in expected or key in projected or item.get("error") or item.get("skipped"):
            raise ValueError("unexpected or unexecuted evidence")
        columns, rows = item.get("columns"), item.get("rows")
        if (
            not isinstance(columns, list)
            or not columns
            or any(not isinstance(column, str) or not column.strip() for column in columns)
            or len(set(columns)) != len(columns)
            or not isinstance(rows, list)
        ):
            raise ValueError("invalid evidence columns")
        clean_rows = []
        for row in rows:
            if isinstance(row, Mapping) and set(row) == set(columns):
                values = tuple(row[column] for column in columns)
            elif isinstance(row, list) and len(row) == len(columns):
                values = tuple(row)
            else:
                raise ValueError("invalid evidence row")
            if any(
                not isinstance(value, (str, int, float, bool, type(None)))
                or isinstance(value, float)
                and not math.isfinite(value)
                for value in values
            ):
                raise ValueError("invalid evidence cell")
            clean_rows.append(values)
        count = item.get("row_count", len(clean_rows))
        truncated = item.get("truncated", False)
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < len(clean_rows)
            or not isinstance(truncated, bool)
        ):
            raise ValueError("invalid evidence count")
        projected[key] = (tuple(columns), tuple(clean_rows), truncated or count > len(clean_rows))
    if set(projected) != expected:
        raise ValueError("missing SQL execution evidence")
    return projected
