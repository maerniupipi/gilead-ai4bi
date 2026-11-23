"""Collapse a long 最近提问 list into a couple of asking-preference notes."""

from __future__ import annotations

import re
import unicodedata

RECENT_QUESTION_LIMIT = 10
RECENT_DIGEST_LIMIT = 2
# Content guard NFKC-normalizes the full-width colon, so both forms are raw.
_RAW_QUESTION_PREFIX = re.compile(r"^问过\s*[:：]")

_FOCUS_GROUPS: tuple[tuple[str, ...], ...] = ()
_METRICS: tuple[tuple[str, ...], ...] = (
    ("金额达成率", "达成率", "A/T", "a/t"),
    ("同比增速", "同比", "YoY", "yoy"),
    ("环比增速", "环比", "QoQ", "qoq"),
    ("HoH 增速", "HoH", "hoh", "半年环比"),
    ("EI", "弹性指数"),
    ("市场份额", "份额"),
    ("销售额", "销量"),
)
_TIMES: tuple[tuple[str, ...], ...] = (
    ("今年 YTD", "YTD", "ytd", "今年"),
    ("2025 年", "2025", "25年"),
    ("2026 年 1 月", "2601", "2026-01"),
)


def is_raw_recent_question(content: str) -> bool:
    text = unicodedata.normalize("NFKC", content).strip()
    return bool(_RAW_QUESTION_PREFIX.match(text))


def digest_recent_questions(questions: list[str]) -> tuple[str, ...]:
    """Turn a pile of asked questions into one or two preference notes."""

    blob = unicodedata.normalize("NFKC", "\n".join(questions)).casefold()
    products = [_canonical(group) for group in _FOCUS_GROUPS if _any_alias(blob, group)]
    metrics = [_canonical(group) for group in _METRICS if _any_alias(blob, group)]
    times = [_canonical(group) for group in _TIMES if _any_alias(blob, group)]
    insights: list[str] = []
    if products:
        insights.append(f"近期常问产品：{'、'.join(products)}。")
    focus: list[str] = []
    if metrics:
        focus.append(f"指标侧重{'、'.join(metrics)}")
    if times:
        focus.append(f"时间口径多见{'、'.join(times)}")
    if focus:
        insights.append("近期提问偏好：" + "；".join(focus) + "。")
    if not insights:
        insights.append("近期多次追问同一主题，回答时优先沿用已出现的产品和时间范围。")
    return tuple(insights[:RECENT_DIGEST_LIMIT])


def _canonical(group: tuple[str, ...]) -> str:
    return group[0]


def _any_alias(blob: str, group: tuple[str, ...]) -> bool:
    return any(unicodedata.normalize("NFKC", alias).casefold() in blob for alias in group)


def looks_like_digest(content: str) -> bool:
    return bool(re.match(r"近期(?:常问|提问偏好|多次追问)", content))
