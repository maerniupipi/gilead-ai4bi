"""Compose read-only analyses exclusively over atomic SQL issued by the platform."""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope


# These are relational operations over returned columns. New business measures or
# access to another source must go through the platform's atomic SQL laboratory.
_ANALYSIS_NODES = frozenset("""
select union intersect except with cte from table identifier tablealias column star alias distinct join subquery
where group having order ordered limit offset window windowspec partition
literal null boolean paren add sub mul div mod neg eq neq gt gte lt lte and or not
between in is like ilike case if coalesce nullif sum count avg min max round abs
greatest least lag lead rank denserank rownumber firstvalue lastvalue nullsafeeq nullsafeneq
cast datatype datatypeparam
""".split())
_CAST_TYPES = {"BIGINT", "INT", "DECIMAL", "DOUBLE", "FLOAT", "TEXT", "VARCHAR", "DATE", "TIMESTAMP", "BOOLEAN"}


def generated_queries(records):
    """Stable names for this run, including artifacts created before refs existed."""
    queries = {}
    for record in records:
        data = record.get("payload") or {}
        if record.get("ok") and isinstance(data.get("sql"), str) and data["sql"].strip():
            ref = data.get("sql_ref") or f"q{len(queries) + 1}"
            queries[ref] = data["sql"].strip().removesuffix(";").rstrip()
    return queries


def resolve_query(requested, records):
    queries = generated_queries(records)
    if not queries:
        raise ValueError("本轮还没有实验室生成的 SQL。请先用 generate_sql 提交原子问题。")
    if not requested:
        latest = records[-1]
        if not latest.get("ok") or not (latest.get("payload") or {}).get("sql"):
            raise ValueError("最近的 SQL 实验室请求未生成 SQL。请补全问题后重新生成。")
        requested = next(reversed(queries))
    if requested in queries:
        return queries[requested], [requested]
    for ref, sql in queries.items():
        if requested == sql:
            return sql, [ref]
    try:
        statements = sqlglot.parse(requested, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
            raise ValueError("分析 SQL 必须是一条 SELECT 查询。")
        tree = statements[0]
        if (any(n.key not in _ANALYSIS_NODES for n in tree.walk()) or
                any(n.this.value not in _CAST_TYPES for n in tree.find_all(exp.DataType))):
            raise ValueError("请只对原子结果做筛选、连接、比较、聚合或排序。基础口径交给 generate_sql。")
        if any(s.args.get("from_") is None for s in tree.find_all(exp.Select)):
            raise ValueError("每段分析都需要 FROM 本轮原子结果。")
        if any(re.fullmatch(r"q[0-9]+", c.alias_or_name, re.I) for c in tree.find_all(exp.CTE)):
            raise ValueError("q 加数字是平台原子结果编号，请为分析中的 WITH 子查询使用其他名称。")
        if any(w.args.get("recursive") for w in tree.find_all(exp.With)):
            raise ValueError("原子结果分析仅支持非递归 WITH 子查询。")
        refs = []
        for block in traverse_scope(tree):
            for _, table in block.selected_sources.values():
                if isinstance(table, exp.Table):
                    ref = table.name.lower()
                    if (not isinstance(table.this, exp.Identifier) or table.db or table.catalog
                            or ref not in queries or (table.this.quoted and table.name != ref)):
                        raise ValueError("分析只能引用本轮 SQL 实验室返回的编号：" + "、".join(queries))
                    if ref not in refs:
                        refs.append(ref)
        if not refs:
            raise ValueError("请引用本轮实验室返回的 q1、q2 等原子结果。")
        # Render the validated outer AST, never an unchecked fragment from the model.
        existing = tree.args.get("with_")
        tree.set("with_", None)
        outer = tree.sql(dialect="postgres", comments=False)
    except SqlglotError as exc:
        raise ValueError("请检查分析 SQL 的 PostgreSQL 语法。") from exc
    sources = [f"{ref} AS (\n{queries[ref]}\n)" for ref in refs]
    if existing:
        sources.extend(cte.sql(dialect="postgres", comments=False) for cte in existing.expressions)
    return "WITH " + ",\n".join(sources) + "\n" + outer, refs


_SQL_TEXT = re.compile(r"```(?:sql|postgres(?:ql)?)\b|\bselect\s+(?:distinct\s+)?[^;]{1,1500}?\s+from\b|(?:^|\n)\s*(?:select\b|with\s+\w+\s+as\s*\()", re.I | re.S)
_SQL_TOKEN = re.compile(r"\[\[SQL:(q[1-9][0-9]*|result)\]\]", re.I)
_FENCED_REF = re.compile(r"```(?:sql|postgres(?:ql)?)?\s*(\[\[SQL:(?:q[1-9][0-9]*|result)\]\])\s*```", re.I)


def render_sql_answer(text, artifacts, run_id):
    """Only expose SQL text copied from a current platform or executed-query record."""
    if not _SQL_TOKEN.search(text) and not _SQL_TEXT.search(text):
        return text
    sources = generated_queries(artifacts.tool_records(run_id, "generate_sql"))
    if not sources:
        raise ValueError("先用 generate_sql 取得本轮原子 SQL，再用 [[SQL:q1]] 展示。")
    for record in reversed(artifacts.tool_records(run_id, "query_db")):
        data = record.get("payload") or {}
        if record.get("ok") and data.get("sql") and data.get("source_sql_refs"):
            sources["result"] = data["sql"]
            break
    text = _FENCED_REF.sub(r"\1", text)
    if _SQL_TEXT.search(text):
        # A model may copy or reformat SQL instead of emitting a reference.
        # Only render the server's stored SQL, never the draft in the message.
        distinct = set(sources.values())
        if len(distinct) == 1:
            return "```sql\n" + next(iter(distinct)) + "\n```"
        for ref, sql in sources.items():
            text = text.replace("```sql\n" + sql + "\n```", "[[SQL:" + ref + "]]")
    if _SQL_TEXT.search(text) or any(m[1].lower() not in sources for m in _SQL_TOKEN.finditer(text)):
        raise ValueError("用 [[SQL:q1]] 等本轮有效编号展示原子 SQL，或用 [[SQL:result]] 展示已执行的组合 SQL。")
    return _SQL_TOKEN.sub(lambda match: "```sql\n" + sources[match[1].lower()] + "\n```", text)
