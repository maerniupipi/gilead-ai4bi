"""Local text-to-SQL and field-recall tools.

These replace VPN-bound lab / Bailian calls when a data source is configured:
inspect schema, generate SQL with the chat model, validate with SQLGlot, and
recall columns / distinct values from the selected tables.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from xiaoying_quick.infrastructure.llm.errors import LlmError
from xiaoying_quick.infrastructure.source_db.local_catalog import (
    LocalSourceError,
    LocalSourceGateway,
    format_field_recall,
    format_value_recall,
    validate_sql_against_schema,
)
from xiaoying_quick.modules.agent import AgentToolContext, ToolCallResult, ToolSpec

_GENERATE_SYSTEM = """\
你是本地 SQL 生成器。根据给定的表结构和参考信息，把原子化查数问题写成只读 SELECT。
只输出 JSON 对象，形状：
{"candidates":[{"candidate_no":1,"sql":"SELECT ...","narrative":"一句话理解"}]}
规则：
- 只能使用参考信息里出现的表、字段、枚举值，禁止编造。
- 只写 SELECT，禁止写操作、SELECT *、SELECT INTO、加锁。
- 一条候选即可，最多 3 条。
- 不要执行 SQL，也不要解释过程。
"""


def _gateway(context: AgentToolContext) -> LocalSourceGateway:
    return context.dependency("local_source")


def _missing_source() -> ToolCallResult:
    return ToolCallResult(
        ok=False,
        output="本地数据源未配置。请先在工具目录打开「数据库查询」，填写连接并勾选表。",
    )


def build_inspect_schema_tool() -> ToolSpec:
    """Dump DDL and comments for the tables the admin selected."""

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        raw = arguments.get("tables")
        tables: list[str] | None = None
        if isinstance(raw, (list, tuple)):
            tables = [str(item).strip() for item in raw if str(item).strip()]
        elif str(arguments.get("tables") or "").strip():
            tables = [
                part.strip()
                for part in str(arguments.get("tables")).split(",")
                if part.strip()
            ]
        try:
            catalog = _gateway(context).inspect(tables)
        except LookupError:
            return _missing_source()
        except LocalSourceError as exc:
            return ToolCallResult(ok=False, output=str(exc))
        except Exception as exc:  # noqa: BLE001 — observation for the model
            return ToolCallResult(ok=False, output=f"读取表结构失败：{str(exc)[:800]}")
        ddl = catalog.format_ddl()
        names = [table.name for table in catalog.tables]
        return ToolCallResult(
            ok=True,
            output=f"已读取 {len(names)} 张表的结构（含字段注释，如有）：\n```sql\n{ddl}\n```",
            payload={
                "tables": names,
                "ddl": ddl,
                "database": catalog.database,
                "dialect": catalog.dialect,
            },
        )

    return ToolSpec(
        name="inspect_schema",
        description=(
            "读取已配置数据源里勾选表的结构：表名、字段、类型、注释。"
            "生成 SQL 之前先调用，避免编造表名或字段。"
            "可选 tables 限定子集；默认读取配置里勾选的全部表。"
            "只返回结构，不返回数据行。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选。只看这些表；留空表示已勾选的全部表",
                },
            },
        },
        executor=execute,
    )


def build_validate_sql_tool() -> ToolSpec:
    """SQLGlot syntax + schema qualify, like the reference text-to-sql agent."""

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        sql = str(arguments.get("sql") or "").strip().rstrip(";").strip()
        if not sql:
            return ToolCallResult(ok=False, output="缺少必填参数 sql。")
        try:
            catalog = _gateway(context).inspect()
        except LookupError:
            return _missing_source()
        except LocalSourceError as exc:
            return ToolCallResult(ok=False, output=str(exc))
        ok, errors = validate_sql_against_schema(sql, schema=catalog, dialect=catalog.dialect)
        if ok:
            return ToolCallResult(
                ok=True,
                output="SQL 校验通过（语法与字段均能在已勾选表结构中对应）。",
                payload={"sql": sql, "valid": True, "errors": []},
            )
        joined = "；".join(errors)
        return ToolCallResult(
            ok=False,
            output=f"SQL 校验失败：{joined}。请根据错误修正后再次 generate_sql 或 validate_sql。",
            payload={"sql": sql, "valid": False, "errors": list(errors)},
        )

    return ToolSpec(
        name="validate_sql",
        description=(
            "用 SQLGlot 校验一条 SELECT：语法、是否只读、表和字段是否存在于已勾选结构。"
            "generate_sql 之后必须校验；失败则带着错误再生成，不要直接交给 query_db。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "待校验的只读 SELECT"},
            },
            "required": ["sql"],
        },
        executor=execute,
    )


def build_generate_sql_tool(allowed_labs: Sequence[str]) -> ToolSpec:
    """Ask the chat model to write candidate SQL from schema + optional context."""

    lab_ids = tuple(allowed_labs)

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        question = str(arguments.get("question") or "").strip()
        if not question:
            return ToolCallResult(ok=False, output="缺少必填参数 question（原子化的查数问题）。")
        lab_id = str(arguments.get("lab_id") or "").strip()
        extra = str(arguments.get("context") or "").strip()
        try:
            catalog = _gateway(context).inspect()
        except LookupError:
            return _missing_source()
        except LocalSourceError as exc:
            return ToolCallResult(ok=False, output=str(exc))
        try:
            client = context.dependency("llm_client")
        except LookupError:
            return ToolCallResult(ok=False, output="无法调用模型，SQL 生成不可用。")
        user_prompt = _generate_user_prompt(
            question=question,
            lab_id=lab_id,
            extra=extra,
            ddl=catalog.format_ddl(),
            dialect=catalog.dialect,
        )
        try:
            completion = await client.complete_json(
                purpose="sql.generate",
                system_prompt=_GENERATE_SYSTEM,
                user_prompt=user_prompt,
                max_tokens=2_048,
            )
        except LlmError as exc:
            return ToolCallResult(ok=False, output=f"SQL 生成失败：{exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(ok=False, output=f"SQL 生成失败：{str(exc)[:800]}")
        records = _parse_candidates(completion.payload)
        if not records:
            return ToolCallResult(
                ok=False,
                output="模型没有返回可用的候选 SQL。请补充 context 或 inspect_schema 后再试。",
                payload={"question": question, "lab_id": lab_id, "candidates": []},
            )
        first_sql = records[0]["sql"]
        ok, errors = validate_sql_against_schema(
            first_sql, schema=catalog, dialect=catalog.dialect
        )
        lines = [f"本地生成了 {len(records)} 条候选 SQL（方言 {catalog.dialect}）："]
        for item in records:
            lines.append(f"\n候选 {item['candidate_no']}：\n```sql\n{item['sql']}\n```")
            if item["narrative"]:
                lines.append(f"理解：{item['narrative'][:600]}")
        if ok:
            lines.append(
                "\n第一条已通过 SQLGlot 校验。仍须由主智能体用 query_db 执行后才能作为事实。"
            )
        else:
            joined = "；".join(errors)
            lines.append(f"\n注意：第一条未通过校验：{joined}。请修正后再 validate_sql。")
        return ToolCallResult(
            ok=True,
            output="\n".join(lines),
            payload={
                "lab_id": lab_id,
                "question": question,
                "candidates": records,
                "sql": first_sql,
                "validated": ok,
                "errors": list(errors),
            },
        )

    properties: dict[str, Any] = {
        "question": {
            "type": "string",
            "description": "原子化查数问题：单一意图，含产品 / 时间 / 口径",
        },
        "lab_id": {
            "type": "string",
            "description": "可选。actual / demand / ext_simple / ext_complex",
        },
        "context": {
            "type": "string",
            "description": "已召回的参考信息：字段取值、口径、时间锚点、KPI。不要塞整份文档。",
        },
    }
    if lab_ids:
        properties["lab_id"]["enum"] = list(lab_ids)
    return ToolSpec(
        name="generate_sql",
        description=(
            "根据已读取的表结构和参考信息，在本地生成候选 SQL。"
            "调用前应 inspect_schema，并把口径/词条放进 context。"
            "返回候选后用 validate_sql 校验；不要自己执行，执行交给主智能体 query_db。"
        ),
        parameters={
            "type": "object",
            "properties": properties,
            "required": ["question"],
        },
        executor=execute,
    )


def build_field_recall_tool() -> ToolSpec:
    """Match a query to table/column names and comments."""

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolCallResult(ok=False, output="缺少必填参数 query。")
        lab_type = str(arguments.get("lab_type") or "").strip()
        try:
            hits = _gateway(context).recall_fields(query)
        except LookupError:
            return _missing_source()
        except LocalSourceError as exc:
            return ToolCallResult(ok=False, output=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(ok=False, output=f"字段召回失败：{str(exc)[:800]}")
        text = format_field_recall(hits, query=query)
        header = f"lab_type={lab_type}，" if lab_type else ""
        return ToolCallResult(
            ok=True,
            output=(
                text
                if not lab_type
                else f"字段召回（{header}query={query}）：\n" + text.split("\n", 1)[-1]
            ),
            payload={"query": query, "lab_type": lab_type, "hits": hits, "text": text},
        )

    return ToolSpec(
        name="field_recall",
        description=(
            "把用户问题或短词匹配到已勾选表的字段：按字段名、表名、字段注释打分。"
            "用于确定「院外 / 品牌 / 省份」应对哪一列。只返回字段含义，不返回 SQL，也不返回数字。"
            "需要取值时再调用 value_recall。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户原问题全文，或某个短词",
                },
                "lab_type": {
                    "type": "string",
                    "description": "可选。对应实验室名称，仅用于标注",
                },
            },
            "required": ["query"],
        },
        executor=execute,
    )


def build_value_recall_tool() -> ToolSpec:
    """Probe DISTINCT values on dimension columns that match the query."""

    async def execute(context: AgentToolContext, arguments: Mapping[str, Any]) -> ToolCallResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolCallResult(ok=False, output="缺少必填参数 query。")
        table = str(arguments.get("table") or "").strip() or None
        column = str(arguments.get("column") or "").strip() or None
        try:
            settings = context.dependency("recall_settings")
        except LookupError:
            settings = {"probe_values": True, "max_values": 24}
        if isinstance(settings, Mapping) and settings.get("probe_values") is False:
            return ToolCallResult(
                ok=True,
                output="取值探测已在召回设置里关闭。只用 field_recall 的字段含义，不要猜枚举。",
                payload={"query": query, "groups": [], "text": ""},
            )
        max_values = 24
        if isinstance(settings, Mapping):
            try:
                max_values = int(settings.get("max_values") or 24)
            except (TypeError, ValueError):
                max_values = 24
        max_values = max(1, min(max_values, 100))
        try:
            groups = _gateway(context).recall_values(
                query, table=table, column=column, max_values=max_values
            )
        except LookupError:
            return _missing_source()
        except LocalSourceError as exc:
            return ToolCallResult(ok=False, output=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(ok=False, output=f"取值召回失败：{str(exc)[:800]}")
        text = format_value_recall(groups, query=query)
        return ToolCallResult(
            ok=True,
            output=text,
            payload={
                "query": query,
                "table": table,
                "column": column,
                "groups": groups,
                "text": text,
            },
        )

    return ToolSpec(
        name="value_recall",
        description=(
            "在已勾选表上探测字段取值：对匹配到的维度列做 DISTINCT + LIKE。"
            "query 可以是原问题或短词；已确定字段时可传 table 和 column。"
            "只返回候选值，不返回 SQL，也不返回汇总数字。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户原问题全文，或某个短词"},
                "table": {"type": "string", "description": "可选。限定一张表"},
                "column": {"type": "string", "description": "可选。限定一个字段"},
            },
            "required": ["query"],
        },
        executor=execute,
    )


def _generate_user_prompt(
    *,
    question: str,
    lab_id: str,
    extra: str,
    ddl: str,
    dialect: str,
) -> str:
    from xiaoying_quick.modules.labs.labels import lab_display_name

    lines = [
        f"方言：{dialect}",
        f"实验室：{lab_display_name(lab_id)}",
        f"问题：{question[:2_000]}",
        "表结构：",
        ddl[:8_000],
    ]
    if extra:
        lines.extend(["参考信息：", extra[:4_000]])
    return "\n".join(lines)


def _parse_candidates(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("candidates")
    if not isinstance(raw, list):
        sql = str(payload.get("sql") or "").strip()
        if not sql:
            return []
        raw = [{"sql": sql, "narrative": str(payload.get("narrative") or "")}]
    records: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:3], start=1):
        if not isinstance(item, Mapping):
            continue
        sql = str(item.get("sql") or "").strip().rstrip(";").strip()
        if not sql:
            continue
        records.append(
            {
                "candidate_no": int(item.get("candidate_no") or index),
                "sql": sql,
                "narrative": str(item.get("narrative") or "").strip()[:600],
            }
        )
    return records
