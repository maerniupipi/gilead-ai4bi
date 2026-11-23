"""Generic SQL coverage review: question + confirmed scopes vs SQL text.

No schema names, field names or business rules live here. The judge only
checks whether constraints already stated in the question or ledger leave a
visible trace in the SQL. Uncertain cases must not block a query.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SQL_REVIEW_SYSTEM = (
    "你审查一条候选 SELECT 是否覆盖了「原始问题 + 已确认口径」里已经明确写出的约束。"
    "只根据给定文本判断，禁止编造表名、字段名或业务规则。规则："
    "SQL 若明显是探测数据边界（MAX/MIN 日期、DISTINCT 枚举、只验证表结构），"
    "判定通过，uncertain=true。"
    "问题或已确认口径里的过滤（时间窗口、对象、排除、范围）在 SQL 文本中"
    "完全看不到对应痕迹，列入 missing，ok=false。"
    "看不出字段映射是否正确时，ok=true 且 uncertain=true，不要误杀。"
    '只输出 JSON：{"ok": true, "uncertain": false, "missing": [], "reason": "一句话"}'
)


def build_sql_review_user_prompt(
    *,
    question: str,
    ledger: Sequence[Mapping[str, Any]],
    sql: str,
) -> str:
    """Assemble the user prompt for one coverage review."""

    scopes = [
        str(entry.get("text") or "").strip()
        for entry in ledger
        if str(entry.get("text") or "").strip()
        and str(entry.get("kind") or "") in {"scope", "time", "qualifier", "constant"}
    ]
    lines = [
        f"原始问题：{question.strip()[:800] or '（无）'}",
        "已确认口径：",
    ]
    if scopes:
        lines.extend(f"- {item[:200]}" for item in scopes[:16])
    else:
        lines.append("- （无）")
    lines.append("候选 SQL：")
    lines.append(f"```sql\n{sql.strip()[:4000]}\n```")
    return "\n".join(lines)


def interpret_sql_review(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a model JSON object into a bounded review record."""

    if not isinstance(payload, Mapping):
        return {"ok": True, "uncertain": True, "missing": [], "reason": "审查不可用"}
    missing_raw = payload.get("missing")
    missing = (
        [str(item).strip()[:120] for item in missing_raw if str(item).strip()]
        if isinstance(missing_raw, list)
        else []
    )
    ok = bool(payload.get("ok", True))
    if missing and payload.get("ok") is False:
        ok = False
    reason = str(payload.get("reason") or "").strip()[:200]
    return {
        "ok": ok,
        "uncertain": bool(payload.get("uncertain")),
        "missing": missing[:8],
        "reason": reason,
    }


def format_sql_review_notice(review: Mapping[str, Any]) -> str:
    """One observation block appended to a query_db tool result."""

    if not review.get("ok"):
        missing = "；".join(str(item) for item in review.get("missing") or []) or "未列出"
        reason = str(review.get("reason") or "").strip()
        suffix = f" {reason}" if reason else ""
        return (
            "\n口径审查未通过：SQL 可能缺少已确认约束（"
            + missing
            + "）。查询行仅供参考，不可作为最终事实，请补条件后重查或换问法重问实验室。"
            + suffix
        )
    if review.get("uncertain"):
        reason = str(review.get("reason") or "无法从文本判定字段映射").strip()
        return f"\n口径审查：未发现明显缺失，但有不确定项（{reason}）。"
    return "\n口径审查：已确认约束在 SQL 中可见。"
