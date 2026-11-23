"""The tools exposed to the agent loop.

- ``ask_lab``          — mandatory; asks a Quick Lab for candidate SQL;
- ``query_db``         — mandatory; runs read-only SQL through the AZAI API;
- ``export_xlsx``      — export the full last query_db result as a downloadable workbook;
- ``knowledge_search`` — recall local markdown knowledge / lab documents / memory;
- ``bailian_recall``   — recall platform knowledge (terms, fields) via AZAI 查数;
- ``knowledge_read``   — browse the knowledge tree by relative path;
- ``memory_save``      — persist a durable scope/preference the user stated;
- ``ask_user``         — suspend the loop for a clarification.
- ``update_ledger``    — project concise progress for the user.

Executors only see ``AgentToolContext``: dependencies arrive through
``context.dependency(...)``, wired by the container, so the specs themselves
are reusable across runs and tests.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot.errors import ParseError

from xiaoying_quick.infrastructure.result_xlsx import MAX_EXPORT_ROWS, dump_result_xlsx
from xiaoying_quick.modules.agent import AgentToolContext, ToolCallResult, ToolSpec
from xiaoying_quick.modules.context import (
    ContextBroker,
    RecallLevel,
    RecallRequest,
    RecallSourceType,
)
from xiaoying_quick.modules.knowledge import CandidateRequest, KnowledgeScope, MemoryWriteRequest
from xiaoying_quick.modules.labs import LabRequest
from xiaoying_quick.modules.labs.contracts import LabContractError
from xiaoying_quick.modules.labs.knowledge_pack import format_upstream_context, pack_from_documents
from xiaoying_quick.modules.labs.lab_features import (
    build_call_features,
    sales_anchor,
    time_anchor_text,
)
from xiaoying_quick.shared.ids import new_id

#: Rows the model gets to see in context; the full set stays in the payload.
_MODEL_VISIBLE_ROWS = 30
_KNOWLEDGE_READ_CHARS = 20_000
#: knowledge_search drops personal memory when the run asked for a clean slate.
_KNOWLEDGE_SOURCES_WITHOUT_MEMORY = frozenset(
    {
        RecallSourceType.SESSION_STATE,
        RecallSourceType.BUSINESS_KNOWLEDGE,
        RecallSourceType.DOMAIN_KNOWLEDGE,
        RecallSourceType.RUNTIME_PARAMETER,
        RecallSourceType.LAB_CONSTRAINT,
        RecallSourceType.SCHEMA_CARD,
        RecallSourceType.SQL_POLICY,
    }
)


def _lab_context_meta(context: AgentToolContext) -> dict[str, Any]:
    try:
        provider = context.dependency("lab_provider")
        mock_enabled = bool(context.dependency("lab_mock_enabled"))
    except LookupError:
        return {}
    return {"lab_provider": provider, "mock_enabled": mock_enabled} if provider else {}


def build_ask_lab_tool(
    allowed_labs: Sequence[str],
    *,
    knowledge_root: Path,
    max_sales_month: str | None = None,
) -> ToolSpec:
    """Ask one laboratory to turn an atomized question into candidate SQL."""

    lab_ids = tuple(allowed_labs)

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        question = str(arguments.get("question") or "").strip()
        if not question:
            return ToolCallResult(ok=False, output="缺少必填参数 question（原子化的业务问题）。")
        lab_id = str(arguments.get("lab_id") or "").strip()
        if lab_id not in lab_ids:
            return ToolCallResult(
                ok=False,
                output=f"lab_id 必须是 {' / '.join(lab_ids)} 之一。",
            )
        lab = context.dependency("lab")
        # The lab templates reference features.* placeholders and every value
        # is ours to ship: time anchors, ambiguity knowledge, KPI logic plus
        # the five loop_prompt slots (glossary, confirmed scopes, time anchor,
        # KPI formulas, reserved).
        remark = str(arguments.get("remark") or "")
        attach_upstream = bool(arguments.get("attach_upstream"))
        features = build_call_features(
            lab_id=lab_id,
            knowledge_root=knowledge_root,
            max_sales_month=max_sales_month,
            remark=remark,
        )
        anchor_year, anchor_month = sales_anchor(max_sales_month)
        confirmed = {
            f"已确认口径{index}": scope
            for index, scope in enumerate(context.active_scopes, start=1)
        }
        upstream_context = ""
        if attach_upstream:
            try:
                hops = list(context.dependency("upstream_hops") or [])
            except LookupError:
                hops = []
            if hops:
                upstream_context = format_upstream_context(hops[-1])
        loop_prompts = pack_from_documents(
            knowledge_root=knowledge_root,
            lab_id=lab_id,
            query=question,
            confirmed=confirmed,
            time_anchor=time_anchor_text(anchor_year, anchor_month),
            upstream_context=upstream_context,
        )
        from xiaoying_quick.modules.labs.labels import lab_display_name

        lab_label = lab_display_name(lab_id)
        query_text = question[:2_000]
        try:
            provider = context.dependency("lab_provider")
        except LookupError:
            provider = None
        if provider == "bootcamp" and remark.strip():
            # Bootcamp's native gateway reads content; features.remark alone is
            # not a binding input to its SQL template. Keep confirmed filters
            # in that same bounded question so generation and trace identity agree.
            query_text = question[:1_200] + "\n\n已确认查询条件：\n" + remark.strip()[:750]
        try:
            candidates = await lab.generate_sql(
                LabRequest(
                    atom_id=new_id("atom"),
                    lab_id=lab_id,
                    query=query_text,
                    session_params={**features, **loop_prompts},
                )
            )
        except LabContractError as exc:
            return ToolCallResult(ok=False, output=f"实验室 {lab_label} 返回不可用：{exc.message}")
        if not candidates:
            return ToolCallResult(
                ok=False,
                output=f"实验室 {lab_label} 未生成任何候选 SQL，请换一种问法或改用其他工具。",
                payload={"lab_id": lab_id, "candidates": []},
            )
        try:
            persist_evidence = context.dependency("lab_evidence_checkpoint")
        except LookupError:
            persist_evidence = None
        if callable(persist_evidence):
            persist_evidence()
        source = _lab_context_meta(context)
        prefix = "演示数据 · " if source.get("mock_enabled") else ""
        lines = [f"{prefix}实验室 {lab_label} 生成了 {len(candidates)} 条候选 SQL："]
        records = []
        for candidate in candidates:
            lines.append(f"\n候选 {candidate.candidate_no}：\n```sql\n{candidate.sql}\n```")
            if candidate.narrative.strip():
                lines.append(f"理解：{candidate.narrative.strip()[:600]}")
            records.append(
                {
                    "candidate_no": candidate.candidate_no,
                    "sql": candidate.sql,
                    "narrative": candidate.narrative,
                }
            )
        lines.append("\n提示：候选 SQL 需要先用 query_db 执行验证，再据此回答。")
        if attach_upstream and upstream_context:
            lines.append("已把上一跳已核验 SQL 与结果写入实验室 loop_prompt_5。")
        elif attach_upstream:
            lines.append(
                "注意：attach_upstream=true，但本轮还没有已核验的上一跳查询，loop_prompt_5 为空。"
            )
        lab_session_id = next(
            (candidate.session_id for candidate in candidates if candidate.session_id), ""
        )
        return ToolCallResult(
            ok=True,
            output="\n".join(lines),
            payload={
                **source,
                "lab_id": lab_id,
                "question": question,
                "candidates": records,
                "loop_prompts": loop_prompts,
                "lab_session_id": lab_session_id,
                "attach_upstream": attach_upstream,
            },
        )

    enum = list(lab_ids)
    return ToolSpec(
        name="ask_lab",
        description=(
            "调用实验室：把一个原子化的查数问题交给指定实验室，产出候选 SQL 及其理解说明。"
            "只接受答案可从数据库取出的查数问题（含产品/时间/维度/指标）；"
            "定义、口径、术语含义等知识性问题不要问实验室，"
            "应改用 knowledge_search / knowledge_read，文档没有再用 ask_user 澄清。"
            "返回的 SQL 是候选，必须再用 query_db 执行后才能作为事实。"
            "嵌套/递进的下一跳设 attach_upstream=true，系统会把上一跳已执行 SQL 与结果写入 "
            "loop_prompt_5；不要自己把上一跳名单抄进问句。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "原子化问题：单一意图、包含产品/时间/口径等关键要素",
                },
                "lab_id": {"type": "string", "enum": enum, "description": "目标实验室"},
                "remark": {
                    "type": "string",
                    "description": (
                        "可选：本次问题的补充备注，如已确认的口径、"
                        "上一步结论代入的上下文（机构/市场/时间窗口等）"
                    ),
                },
                "attach_upstream": {
                    "type": "boolean",
                    "description": (
                        "本问要以上一跳已核验的结果集为过滤条件时为 true。"
                        "为 true 时由系统写入 loop_prompt_5，不要把名单抄进 question。"
                        "第一跳或与上一跳无关时必须为 false。"
                    ),
                },
            },
            "required": ["question", "lab_id"],
        },
        executor=execute,
    )


def build_query_db_tool() -> ToolSpec:
    """Run one read-only SELECT against the configured local data source."""

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        sql = str(arguments.get("sql") or "").strip().rstrip(";").strip()
        if not sql:
            return ToolCallResult(ok=False, output="缺少必填参数 sql。")
        source = _lab_context_meta(context)
        dialect = "postgres" if source.get("lab_provider") == "gilead" else "mysql"
        rejection = _check_select_only(sql, dialect)
        if rejection is not None:
            return ToolCallResult(ok=False, output=rejection)
        query = context.dependency("query_db")
        try:
            columns, rows, truncated, duration_ms = query(sql, MAX_EXPORT_ROWS)
            adapter = getattr(query, "__self__", None)
            if callable(getattr(adapter, "source_for", None)):
                source.update(adapter.source_for(sql))
        except Exception as exc:  # noqa: BLE001 — surfaced to the model as a fact.
            return ToolCallResult(
                ok=False,
                output=(
                    f"SQL 执行失败：{str(exc)[:800]}。请检查表名/字段，或换问法再 generate_sql。"
                ),
                payload={"sql": sql},
            )
        if not columns and not rows:
            return ToolCallResult(
                ok=True,
                output="查询成功，但结果为空（没有匹配的数据）。可尝试放宽条件或更换口径。",
                payload={**source, "sql": sql, "columns": [], "rows": [], "truncated": False},
            )
        visible = rows[:_MODEL_VISIBLE_ROWS]
        table = ["| " + " | ".join(str(column) for column in columns) + " |"]
        table.append("|" + "---|" * len(columns))
        table.extend("| " + " | ".join(_cell_text(cell) for cell in row) + " |" for row in visible)
        notes = []
        if len(rows) > len(visible):
            notes.append(f"仅展示前 {len(visible)} 行，共 {len(rows)} 行")
            notes.append("完整结果请调用 export_xlsx 导出给用户下载，不要把行数据抄进参数")
        if truncated:
            notes.append("结果集超过上限，已截断")
        suffix = f"\n（{'；'.join(notes)}）" if notes else ""
        header = f"查询成功，共 {len(rows)} 行，耗时 {duration_ms}ms：\n"
        if source.get("mock_enabled"):
            header = "演示数据（模拟生成，非真实业务结果）\n" + header
        elif source.get("lab_provider") == "bootcamp":
            header = "Bootcamp 平台已执行的 SQL 证据\n" + header
        return ToolCallResult(
            ok=True,
            output=header + "\n".join(table) + suffix,
            payload={
                **source,
                "sql": sql,
                "columns": list(columns),
                "rows": [list(row) for row in rows],
                "truncated": truncated,
                "duration_ms": duration_ms,
            },
        )

    return ToolSpec(
        name="query_db",
        description=(
            "数据库查询：对已配置的本地数据源执行一条只读 SELECT，返回列与数据行。"
            "只允许查询配置里勾选的表。未配置本地连接时，若环境提供了 AZAI 则回退远程查询。"
            "只允许单条 SELECT；执行失败或结果为空时应观察原因并调整 SQL 或换用其他工具。"
            "返回给你的表格最多 30 行；超过 30 行时必须再调用 export_xlsx 把完整结果交给用户下载。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "一条完整的只读 SELECT 语句"},
            },
            "required": ["sql"],
        },
        executor=execute,
    )


def build_export_xlsx_tool() -> ToolSpec:
    """Export the last verified query_db payload as a downloadable xlsx."""

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        title = str(arguments.get("title") or "").strip()
        if not title:
            return ToolCallResult(ok=False, output="缺少必填参数 title（这个问题是什么）。")
        summary = str(arguments.get("summary") or "").strip()
        table = _select_export_table(context)
        if table is None:
            return ToolCallResult(
                ok=False,
                output="还没有可导出的查询结果。请先用 query_db 取数，再调用 export_xlsx。",
            )
        if table.get("mock_enabled"):
            title = f"【演示数据】{title}"
            summary = "模拟生成，非真实业务结果。" + summary
        columns = list(table["columns"])
        rows = list(table["rows"])[:MAX_EXPORT_ROWS]
        filename = _export_filename(title)
        try:
            artifacts = context.dependency("artifacts")
        except LookupError:
            return ToolCallResult(ok=False, output="导出服务不可用，无法生成下载文件。")
        try:
            dump_result_xlsx(title=title, summary=summary, columns=columns, rows=rows)
        except ValueError as exc:
            return ToolCallResult(ok=False, output=f"无法生成工作簿：{exc}")
        export_id = artifacts.append(
            run_id=context.run_id,
            kind="xlsx_export",
            payload={
                "filename": filename,
                "title": title,
                "summary": summary,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": bool(table.get("truncated")) or len(table["rows"]) > MAX_EXPORT_ROWS,
            },
        )
        download_path = f"/api/v2/runs/{context.run_id}/exports/{export_id}"
        notes = [f"已导出完整结果，共 {len(rows)} 行。"]
        if table.get("truncated") or len(table["rows"]) > MAX_EXPORT_ROWS:
            notes.append("源查询结果曾被截断，工作簿只包含当前保留的行。")
        notes.append(f"请把下面的下载链接交给用户：[{filename}]({download_path})")
        notes.append("聊天里只展示前 30 行，完整数据以工作簿为准。")
        return ToolCallResult(
            ok=True,
            output="\n".join(notes),
            payload={
                "filename": filename,
                "title": title,
                "summary": summary,
                "row_count": len(rows),
                "download_path": download_path,
                "export_id": export_id,
            },
        )

    return ToolSpec(
        name="export_xlsx",
        description=(
            "xlsx 导出：把本轮已核验 query_db 里行数最多的那份完整结果写成工作簿，"
            "并返回下载链接。后面如果还有 1 行探测查询，仍导出前面那份大结果，"
            "不要把探测查询当成最终表。"
            "聊天和本工具都不会把全部行写进上下文；超过 30 行的最终取数必须调用本工具。"
            "title 写这个问题是什么，summary 写结果的简要说明（口径/时间/行数等）。"
            "不要传行数据。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "这个问题是什么，写入工作簿第一行合并单元格",
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "结果的简要说明（口径、时间范围、行数等），与 title 一起写入第一行"
                    ),
                },
            },
            "required": ["title"],
        },
        executor=execute,
    )


def snapshot_query_table(
    payload: Mapping[str, Any], *, question: str = ""
) -> dict[str, Any] | None:
    """Keep the full query_db grid for export; hops may still clip rows for labs."""

    columns = payload.get("columns")
    rows = payload.get("rows")
    if not isinstance(columns, list) or not columns or not isinstance(rows, list):
        return None
    normalized_rows = [
        list(row) if isinstance(row, (list, tuple)) else [row] for row in rows[:MAX_EXPORT_ROWS]
    ]
    return {
        "question": str(question or "")[:500],
        "sql": str(payload.get("sql") or "")[:4_000],
        "columns": [str(column) for column in columns[:64]],
        "rows": normalized_rows,
        "row_count": len(rows),
        "truncated": bool(payload.get("truncated")) or len(rows) > MAX_EXPORT_ROWS,
        "mock_enabled": bool(payload.get("mock_enabled")),
    }


def _select_export_table(context: AgentToolContext) -> dict[str, Any] | None:
    """Prefer the largest verified grid, not a later 1-row probe."""

    try:
        tables = list(context.dependency("query_tables") or [])
    except LookupError:
        tables = []
    snapshots: list[dict[str, Any]] = []
    for item in tables:
        if not isinstance(item, Mapping):
            continue
        snapshot = snapshot_query_table(item, question=str(item.get("question") or ""))
        if snapshot is not None:
            snapshots.append(snapshot)
    if not snapshots:
        return None
    return max(
        enumerate(snapshots),
        key=lambda pair: (int(pair[1]["row_count"]), pair[0]),
    )[1]


def _export_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', " ", title)
    cleaned = " ".join(cleaned.split()).strip() or "查询结果"
    return f"{cleaned[:60]}.xlsx"


def _check_select_only(sql: str, dialect: str = "mysql") -> str | None:
    try:
        expressions = sqlglot.parse(sql, read=dialect)
    except (ParseError, ValueError):
        return "SQL 无法解析：请检查语法和方言。"
    statements = []
    for expression in expressions:
        if expression is None:
            continue
        kind = expression.key.casefold()
        normalized = expression.sql(
            dialect=dialect, pretty=False, normalize=True, comments=False
        ).strip()
        if kind == "semicolon" and not normalized:
            continue
        statements.append(expression)
    if len(statements) != 1:
        return "一次只允许执行一条 SQL 语句。"
    statement = statements[0]
    read_kinds = {"select", "union", "intersect", "except"} if dialect == "postgres" else {"select"}
    if statement.key.casefold() not in read_kinds:
        return "只允许只读的 SELECT 语句。"
    node_kinds = {node.key.casefold() for node in statement.walk()}
    if "into" in node_kinds:
        return "禁止 SELECT INTO。"
    if "lock" in node_kinds:
        return "禁止加锁读取（FOR UPDATE / LOCK IN SHARE MODE）。"
    forbidden = {"insert", "update", "delete", "drop", "create", "alter", "truncate", "use"}
    hit = forbidden & node_kinds
    if hit:
        return f"检测到写操作关键字：{', '.join(sorted(hit))}。"
    return None


def build_knowledge_search_tool() -> ToolSpec:
    """Recall business knowledge, lab documents and personal memory."""

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolCallResult(ok=False, output="缺少必填参数 query。")
        broker: ContextBroker = context.dependency("context_broker")
        allowed = None if _memory_enabled(context) else _KNOWLEDGE_SOURCES_WITHOUT_MEMORY
        pack = broker.recall(
            RecallRequest(
                request_id=new_id("recall"),
                level=RecallLevel.L1_UNDERSTANDING,
                actor_id=context.actor_id,
                session_id=context.session_id,
                frame_id=context.run_id,
                query=query[:1_000],
                allowed_source_types=allowed,
            ),
            performed_at=datetime.now(timezone.utc),
        )
        if not pack.items:
            return ToolCallResult(
                ok=True,
                output="未检索到相关知识。可用 knowledge_read 浏览知识目录，或直接向用户确认口径。",
                payload={"query": query, "hits": []},
            )
        lines = [f"检索到 {len(pack.items)} 条相关知识："]
        records = []
        for hit in pack.items[:8]:
            snippet = hit.content.strip()[:1_200]
            lines.append(f"\n【{hit.source_type.value} · {hit.content_id}】\n{snippet}")
            records.append(
                {
                    "source_type": hit.source_type.value,
                    "content_id": hit.content_id,
                    "score": hit.score,
                    "content": snippet,
                }
            )
        return ToolCallResult(
            ok=True,
            output="\n".join(lines),
            payload={"query": query, "hits": records},
        )

    return ToolSpec(
        name="knowledge_search",
        description=(
            "检索知识库：按语义召回业务知识、实验室文档与个人记忆。"
            "在查数前先检索口径/指标定义，可以避免用错口径。"
            "概念/定义类问题只在这里和 knowledge_read 里找答案；"
            "检索不到时用 ask_user 向用户澄清，不要改问实验室。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词：指标名、产品名、口径描述等"},
            },
            "required": ["query"],
        },
        executor=execute,
    )


def build_bailian_recall_tool(allowed_labs: Sequence[str]) -> ToolSpec:
    """Recall platform knowledge (terms/fields) through the AZAI 查数 agent."""

    lab_ids = tuple(allowed_labs)
    enum = list(lab_ids)

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolCallResult(ok=False, output="缺少必填参数 query。")
        lab_type = str(arguments.get("lab_type") or "").strip()
        if lab_ids and lab_type not in lab_ids:
            return ToolCallResult(
                ok=False,
                output=f"lab_type 必须是 {' / '.join(lab_ids)} 之一。",
            )
        if not lab_type:
            return ToolCallResult(ok=False, output="缺少必填参数 lab_type（实验室名称）。")
        try:
            recall = context.dependency("bailian_recall")
            text = str(recall(query, lab_type) or "").strip()
        except LookupError:
            return await _local_recall_fallback(context, query=query, lab_type=lab_type)
        except Exception as exc:  # noqa: BLE001 — surfaced to the model as a fact.
            message = str(exc)[:800]
            if "未配置" in message:
                return await _local_recall_fallback(context, query=query, lab_type=lab_type)
            return ToolCallResult(
                ok=False,
                output=(
                    f"百炼召回失败：{message}。"
                    "可改用 field_recall / value_recall，或 knowledge_search。"
                ),
                payload={"query": query, "lab_type": lab_type},
            )
        if not text:
            return ToolCallResult(
                ok=True,
                output="未召回到相关词条。不要猜字段；需要口径时 ask_user。",
                payload={"query": query, "lab_type": lab_type, "text": ""},
            )
        return ToolCallResult(
            ok=True,
            output=f"百炼召回（lab_type={lab_type}，query={query}）：\n{text}",
            payload={"query": query, "lab_type": lab_type, "text": text},
        )

    properties: dict[str, Any] = {
        "query": {
            "type": "string",
            "description": "召回 query：可以是用户原问题全文，也可以是某个短词",
        },
        "lab_type": {
            "type": "string",
            "description": "对应实验室名称，与 ask_lab 的 lab_id 相同",
        },
    }
    if enum:
        properties["lab_type"]["enum"] = enum
    return ToolSpec(
        name="bailian_recall",
        description=(
            "百炼召回：远程知识 API。未配置时自动改走本地字段/取值召回。"
            "优先使用 field_recall / value_recall。只返回知识，不返回 SQL，也不返回数字。"
        ),
        parameters={
            "type": "object",
            "properties": properties,
            "required": ["query", "lab_type"],
        },
        executor=execute,
    )


async def _local_recall_fallback(
    context: AgentToolContext, *, query: str, lab_type: str
) -> ToolCallResult:
    """When Bailian is off, reuse the local field + value catalog."""

    try:
        gateway = context.dependency("local_source")
    except LookupError:
        return ToolCallResult(
            ok=True,
            output=(
                "百炼召回未配置，本地数据源也未配置。"
                "继续用 knowledge_search / knowledge_read，或 ask_user。"
            ),
            payload={"query": query, "lab_type": lab_type, "text": ""},
        )
    try:
        from xiaoying_quick.infrastructure.source_db.local_catalog import (
            format_field_recall,
            format_value_recall,
        )

        hits = gateway.recall_fields(query)
        settings = {}
        try:
            raw = context.dependency("recall_settings")
            if isinstance(raw, Mapping):
                settings = dict(raw)
        except LookupError:
            settings = {"probe_values": True, "max_values": 24}
        groups = []
        if settings.get("probe_values", True):
            max_values = 24
            try:
                max_values = int(settings.get("max_values") or 24)
            except (TypeError, ValueError):
                max_values = 24
            groups = gateway.recall_values(query, max_values=max(1, min(max_values, 100)))
        parts = [format_field_recall(hits, query=query)]
        if groups:
            parts.append(format_value_recall(groups, query=query))
        text = "\n\n".join(part for part in parts if part).strip()
    except Exception as exc:  # noqa: BLE001
        return ToolCallResult(
            ok=True,
            output=(
                "百炼召回未配置，本地召回也不可用："
                f"{str(exc)[:400]}。继续用 knowledge_search / knowledge_read，或 ask_user。"
            ),
            payload={"query": query, "lab_type": lab_type, "text": ""},
        )
    if not text:
        return ToolCallResult(
            ok=True,
            output="未召回到相关词条。不要猜字段；需要口径时 ask_user。",
            payload={"query": query, "lab_type": lab_type, "text": ""},
        )
    header = (
        f"本地召回（lab_type={lab_type}，query={query}）："
        if lab_type
        else f"本地召回（query={query}）："
    )
    return ToolCallResult(
        ok=True,
        output=f"{header}\n{text}",
        payload={"query": query, "lab_type": lab_type, "text": text, "source": "local"},
    )


def build_knowledge_read_tool(root: Path) -> ToolSpec:
    """Read one knowledge document (or list the tree when path is empty)."""

    # Always work from an absolute root. Relative roots (e.g. ../knowledge_gilead)
    # make rglob yield relative Paths; mixing those with root.resolve() in
    # Path.relative_to raises ValueError ("… is not in the subpath of …").
    base = root.expanduser().resolve()

    def _normalize_relative(raw: str) -> str:
        clean = raw.strip().strip("/").replace("\\", "/")
        while clean.startswith("./"):
            clean = clean[2:]
        # Models sometimes paste cwd-relative prefixes from logs or listings.
        root_name = base.name
        for prefix in (f"../{root_name}/", f"{root_name}/"):
            if clean.startswith(prefix):
                clean = clean[len(prefix) :]
        return clean.lstrip("/")

    def _rel_to_base(path: Path) -> str:
        return str(path.resolve().relative_to(base)).replace("\\", "/")

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        del context
        relative = _normalize_relative(str(arguments.get("path") or ""))
        if not relative:
            entries = sorted(
                _rel_to_base(item) for item in base.rglob("*.md") if item.is_file()
            )
            if not entries:
                return ToolCallResult(ok=True, output="知识目录为空。")
            listed = "\n".join(entries[:200])
            more = f"\n…共 {len(entries)} 个文件" if len(entries) > 200 else ""
            return ToolCallResult(
                ok=True,
                output=f"知识目录（用 path 参数读取具体文件）：\n{listed}{more}",
                payload={"files": entries[:200]},
            )
        target = (base / relative).resolve()
        if base not in target.parents and target != base:
            return ToolCallResult(ok=False, output="path 必须位于知识目录内。")
        if target.suffix != ".md" or not target.is_file():
            # The model often guesses a short path ("labs/ddi.md") while the
            # doc lives under a nested folder; resolve by suffix/name instead
            # of failing, so reading knowledge never burns a step.
            needle = relative.replace("\\", "/")
            matches = sorted(
                item
                for item in base.rglob("*.md")
                if item.name == Path(needle).name
                or _rel_to_base(item).endswith(needle)
            )
            # lab_id may be used as a filename (compat id "actual" → labs/ddi.md).
            if not matches:
                from xiaoying_quick.modules.knowledge.lab_catalog import match_lab_document

                stem = Path(needle).stem
                lab_doc = match_lab_document(base, stem)
                if lab_doc is None and stem:
                    # Also try bare lab_id when path was like "labs/actual.md".
                    lab_doc = match_lab_document(base, stem.split("/")[-1])
                if lab_doc is not None:
                    candidate = (base / lab_doc.path).resolve()
                    if candidate.is_file() and (
                        base in candidate.parents or candidate == base
                    ):
                        matches = [candidate]
            if not matches:
                return ToolCallResult(
                    ok=False,
                    output=(
                        "目标不存在或不是 markdown 知识文档。"
                        "本 POC 实验室文档请读 labs/ddi.md。"
                    ),
                )
            target = matches[0].resolve()
        text = target.read_text(encoding="utf-8", errors="replace")
        clipped = text[:_KNOWLEDGE_READ_CHARS]
        suffix = ""
        if len(text) > _KNOWLEDGE_READ_CHARS:
            suffix = f"\n…[文件较长，已截断，共 {len(text)} 字符]"
        resolved = _rel_to_base(target)
        header = f"文档：{resolved}\n\n" if resolved != relative else ""
        return ToolCallResult(
            ok=True,
            output=header + clipped + suffix,
            payload={"path": resolved, "chars": len(text)},
        )

    return ToolSpec(
        name="knowledge_read",
        description=(
            "读取知识文档：path 为空时列出知识目录下全部 markdown 文件；"
            "传相对路径时返回该文档全文。用于查看实验室说明、业务口径等。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "知识目录内的相对路径（如 labs/ddi.md）；留空表示列出目录",
                },
            },
        },
        executor=execute,
    )


_MEMORY_CATEGORIES = {
    "preference": "个人偏好",
    "scope": "默认口径",
    "metric_definition": "指标定义",
    "terminology": "术语词表",
    "recent": "最近关注",
}

#: Where a reviewed knowledge candidate should land once approved.
_REVIEW_TARGETS = {
    "business": "通用业务知识",
    "actual": "吉利德 DDI 实验室（labs/ddi.md）",
    "demand": "demand 实验室",
    "ext_simple": "外部市场·简单 实验室",
    "ext_complex": "外部市场·复杂 实验室",
}

#: Ledger entry kinds the model may write; the UI renders one tag per kind.
LEDGER_ENTRY_KINDS = {
    "term": "术语映射",
    "constant": "常量",
    "qualifier": "限定条件",
    "formula": "指标公式",
    "scope": "口径结论",
    "time": "时间事实",
}


def build_update_ledger_tool() -> ToolSpec:
    """Write or refresh one progress-ledger entry as understanding grows.

    The loop upserts the entry by ``key``: the first call about an element
    plants it (often as “待确认”), later calls replace it with the resolved
    meaning — so the user watches the question come into focus step by step.
    """

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        del context
        key = str(arguments.get("key") or "").strip()[:40]
        action = str(arguments.get("action") or "update").strip()
        if action == "delete":
            if not key:
                return ToolCallResult(ok=False, output="action=delete 时必须提供 key。")
            return ToolCallResult(
                ok=True,
                output=f"已从台账移除：{key}。",
                payload={"delete_key": key},
            )
        kind = str(arguments.get("kind") or "term").strip()
        text = " ".join(str(arguments.get("text") or "").split()).strip()
        if not key:
            return ToolCallResult(
                ok=False,
                output="缺少必填参数 key（条目主体，如产品名/机构名/指标名）。",
            )
        if kind not in LEDGER_ENTRY_KINDS:
            return ToolCallResult(
                ok=False,
                output=f"kind 必须是 {' / '.join(LEDGER_ENTRY_KINDS)} 之一。",
            )
        if not 2 <= len(text) <= 120:
            return ToolCallResult(ok=False, output="text 需要 2-120 字，写成简短的结论。")
        entry = {"key": key, "kind": kind, "text": text}
        return ToolCallResult(
            ok=True,
            output=f"已更新进度台账：{key}（{LEDGER_ENTRY_KINDS[kind]}）。",
            payload={"entry": entry},
        )

    return ToolSpec(
        name="update_ledger",
        description=(
            "更新进度台账：把你对问题要素的理解记成一条，用户会实时看到。"
            "第一步先把问题拆成要素逐条登记（产品/机构/人群/时间窗口/指标/限定条件），"
            "含义不明的先写“待确认”；之后每弄清一个要素就用相同 key 更新该条；"
            "发现与新问题无关的旧条目时用 action=delete 移除。"
            "条目写简短结论，不写数字和中间结果。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["update", "delete"],
                    "description": (
                        "update=新增或覆盖条目（默认）；delete=移除与新问题无关的旧条目（只需 key）"
                    ),
                },
                "key": {
                    "type": "string",
                    "description": (
                        "条目主体（如“茁乐”“中南大学湘雅医院”“PDOT”）；同 key 的条目会被更新覆盖"
                    ),
                },
                "kind": {
                    "type": "string",
                    "enum": list(LEDGER_ENTRY_KINDS),
                    "description": (
                        "term=术语映射；constant=常量；qualifier=限定条件；"
                        "formula=指标公式；scope=口径结论；"
                        "time=时间事实（如某数据源的数据最新月）"
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "简短结论，如“重度哮喘适应症人群（RESP）”；未弄清时写“待确认”",
                },
            },
            "required": ["key", "kind", "text"],
        },
        executor=execute,
    )


def build_memory_save_tool() -> ToolSpec:
    """Persist one durable scope/preference the user stated in this turn.

    Personal scope writes to the asker's own memory and takes effect at once;
    review scope enters the knowledge review queue, because a shared business
    definition must be approved by a human before it binds everyone else.
    """

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        scope = str(arguments.get("scope") or "").strip()
        if scope not in {"personal", "review"}:
            return ToolCallResult(ok=False, output="scope 必须是 personal 或 review。")
        content = str(arguments.get("content") or "").strip()
        if not 8 <= len(content) <= 2_000:
            return ToolCallResult(
                ok=False, output="content 需要 8-2000 字，写成可独立阅读的完整口径描述。"
            )
        if not _memory_enabled(context):
            return ToolCallResult(
                ok=True,
                output="当前运行已关闭个人记忆，本次未写入记忆或知识审核。",
                payload={"scope": scope, "skipped": True, "reason": "use_memory=false"},
            )
        try:
            if scope == "personal":
                category = str(arguments.get("category") or "preference").strip()
                if category not in _MEMORY_CATEGORIES:
                    category = "preference"
                writer = context.dependency("memory_writer")
                entry = writer.write(
                    context.actor_id,
                    MemoryWriteRequest(
                        category=category,
                        content=content,
                        source_run_id=context.run_id,
                    ),
                )
                return ToolCallResult(
                    ok=True,
                    output=(
                        f"已写入个人记忆（{_MEMORY_CATEGORIES[category]}，立即生效，"
                        f"id={entry.id}），后续问答将自动召回该口径。"
                    ),
                    payload={
                        "scope": "personal",
                        "category": category,
                        "content": content,
                        "entry_id": entry.id,
                    },
                )
            title = str(arguments.get("title") or "").strip()
            if not 2 <= len(title) <= 60:
                return ToolCallResult(ok=False, output="scope=review 时必须提供 2-60 字的 title。")
            target = str(arguments.get("target") or "business").strip()
            if target not in _REVIEW_TARGETS:
                return ToolCallResult(
                    ok=False,
                    output=f"target 必须是 {' / '.join(_REVIEW_TARGETS)} 之一。",
                )
            why = str(arguments.get("why") or "").strip() or "本轮对话中用户确认的口径"
            destination = _REVIEW_TARGETS[target]
            proposer = context.dependency("knowledge_proposer")
            candidate = proposer.propose(
                context.actor_id,
                CandidateRequest(
                    scope=KnowledgeScope.BUSINESS,
                    title=title,
                    content=content,
                    rationale=f"【去向：{destination}】{why}",
                    evidence_refs=(f"run:{context.run_id}", f"target:{target}"),
                    source_run_id=context.run_id,
                ),
            )
            return ToolCallResult(
                ok=True,
                output=(
                    f"已提交知识审核（id={candidate.id}，去向：{destination}）；"
                    "审核通过并发布前，该口径不会自动约束他人的查询。"
                ),
                payload={
                    "scope": "review",
                    "target": target,
                    "title": title,
                    "content": content,
                    "entry_id": candidate.id,
                },
            )
        except Exception as exc:  # noqa: BLE001 — surfaced to the model as a fact.
            return ToolCallResult(
                ok=False,
                output=f"知识沉淀失败：{str(exc)[:400]}。不要重试同样的内容，可改写后再沉淀。",
            )

    return ToolSpec(
        name="memory_save",
        description=(
            "知识沉淀：把用户声明的默认口径、偏好、指标定义或纠偏持久化为可复用知识。"
            "scope=personal 直接写入提问者个人记忆（立即生效）；"
            "scope=review 提交知识审核队列（共享口径/指标定义，人工审核后生效），"
            "并用 target 指定去向（business 或对应实验室）。"
            "只沉淀有复用价值的口径，不要沉淀一次性数字。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["personal", "review"],
                    "description": "personal=仅该用户的偏好/习惯；review=共享业务口径/指标定义",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "完整口径描述：脱离对话上下文也能读懂，含适用范围（产品/时间/机构等）"
                    ),
                },
                "category": {
                    "type": "string",
                    "enum": list(_MEMORY_CATEGORIES),
                    "description": "scope=personal 时的分类，默认 preference",
                },
                "title": {
                    "type": "string",
                    "description": "scope=review 时的短标题（2-60 字）",
                },
                "target": {
                    "type": "string",
                    "enum": list(_REVIEW_TARGETS),
                    "description": (
                        "scope=review 时的去向：business=通用业务知识；"
                        "actual/demand/ext_simple/ext_complex=对应实验室文档；默认 business"
                    ),
                },
                "why": {"type": "string", "description": "沉淀理由（可选）"},
            },
            "required": ["scope", "content"],
        },
        executor=execute,
    )


def build_ask_user_tool(*, recommend_choices: bool = True) -> ToolSpec:
    """Pause the loop and ask the user a multiple-choice question."""

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        del context
        groups = _ask_user_groups(arguments, recommend_choices=recommend_choices)
        if isinstance(groups, ToolCallResult):
            return groups
        multi_select = bool(arguments.get("multi_select"))
        for group in groups:
            group["multi_select"] = multi_select
        # The loop owns the ask_user.opened event: it knows the call id and
        # performs the suspension right after this result comes back.
        return ToolCallResult(
            ok=True,
            output="已向用户提问，等待用户选择后继续。",
            payload={"groups": groups},
            suspended=True,
        )

    recommendation = (
        "recommended_index指定有依据的推荐项，从0起算，无依据时填null。"
        if recommend_choices else "所有选项均由用户明确选择，不预选推荐项。"
    )
    return ToolSpec(
        name="ask_user",
        description=(
            "向用户澄清：当问题存在口径歧义、缺少关键信息、多种合理解读，"
            "或知识出现冲突/多种说法需要用户拍板时，"
            "提出 1-3 个问题，每个问题给出 2-4 个基于真实信息的选项。"
            "why说明歧义及其对结果的影响。"
            f"{recommendation}"
            "多个相互独立的歧义（如时间窗口 + 统计口径）应放进同一次澄清；"
            "需要用户选多个去向/多个口径时，设 multi_select=true。"
            "不要为可自行确定的细节打扰用户。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "maxItems": 3,
                    "description": "1-3 个澄清问题，一次性收敛多个歧义槽位",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "要用户澄清的问题"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "2-4 个候选答案，按推荐程度排序",
                            },
                            "why": {"type": "string", "description": "歧义为何会影响本次结果"},
                            "recommended_index": {
                                "type": ["integer", "null"], "minimum": 0, "maximum": 3,
                                "description": "有依据的推荐选项序号；无推荐填null",
                            },
                        },
                        "required": ["question", "options"],
                    },
                },
                "question": {
                    "type": "string",
                    "description": "兼容写法：单个澄清问题（与 options 搭配）",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "兼容写法：单个问题的 2-4 个候选答案",
                },
                "why": {"type": "string", "description": "歧义为何会影响本次结果"},
                "recommended_index": {
                    "type": ["integer", "null"], "minimum": 0, "maximum": 3,
                    "description": "有依据的推荐选项序号；无推荐填null",
                },
                "multi_select": {
                    "type": "boolean",
                    "description": "true=用户可选多个选项（如沉淀去向多选）；默认 false 单选",
                },
            },
        },
        executor=execute,
    )


def _ask_user_groups(
    arguments: Mapping[str, Any],
    *,
    recommend_choices: bool = True,
) -> list[dict[str, Any]] | ToolCallResult:
    """Normalize the tool arguments into clarify groups (or a rejection)."""

    def group_of(item: Mapping[str, Any]) -> dict[str, Any] | None:
        question = str(item.get("question") or "")
        raw_options = item.get("options")
        options: list[str] = []
        if isinstance(raw_options, list):
            options = [str(item).strip() for item in raw_options if str(item).strip()]
        if not question.strip():
            return None
        if not 2 <= len(options) <= 4:
            return None
        recommended = item.get("recommended_index", 0) if recommend_choices else None
        if recommended is not None and (
            type(recommended) is not int or not 0 <= recommended < len(options)
        ):
            return None
        return {
            "question": question.strip(),
            "options": [
                {"label": label, "recommended": index == recommended}
                for index, label in enumerate(options)
            ],
            "why": str(item.get("why") or "").strip()[:600],
            "allow_free_text": True,
        }

    raw_questions = arguments.get("questions")
    if isinstance(raw_questions, list) and raw_questions:
        if len(raw_questions) > 3:
            return ToolCallResult(ok=False, output="一次最多提 3 个澄清问题。")
        groups: list[dict[str, Any]] = []
        for item in raw_questions:
            if not isinstance(item, Mapping):
                return ToolCallResult(ok=False, output="questions 里每项需含 question 与 options。")
            group = group_of(item)
            if group is None:
                return ToolCallResult(
                    ok=False,
                    output="每个澄清问题需要非空question、2-4个选项及有效的推荐序号或null。"
                )
            groups.append(group)
        return groups

    question = str(arguments.get("question") or "").strip()
    if not question:
        return ToolCallResult(ok=False, output="缺少必填参数 question 或 questions。")
    group = group_of(arguments)
    if group is None:
        return ToolCallResult(ok=False, output="需要2-4个非空选项，推荐序号须在范围内或填null。")
    return [group]


def _memory_enabled(context: AgentToolContext) -> bool:
    """Ordinary runs keep memory on; eval sets extras['use_memory']=False."""

    try:
        return bool(context.dependency("use_memory"))
    except LookupError:
        return True


def _cell_text(cell: Any) -> str:
    if cell is None:
        return "NULL"
    text = str(cell)
    return text if len(text) <= 60 else text[:57] + "..."


__all__ = [
    "build_ask_lab_tool",
    "build_ask_user_tool",
    "build_bailian_recall_tool",
    "build_export_xlsx_tool",
    "build_knowledge_read_tool",
    "build_knowledge_search_tool",
    "build_memory_save_tool",
    "build_query_db_tool",
    "build_update_ledger_tool",
    "snapshot_query_table",
]
