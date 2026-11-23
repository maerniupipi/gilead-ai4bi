from xiaoying_quick.application.agent_run.sql_review import (
    format_sql_review_notice,
    interpret_sql_review,
)


def test_interpret_sql_review_defaults_to_uncertain_pass() -> None:
    review = interpret_sql_review(None)
    assert review["ok"] is True
    assert review["uncertain"] is True


def test_interpret_sql_review_failed_when_missing() -> None:
    review = interpret_sql_review(
        {"ok": False, "uncertain": False, "missing": ["时间窗口"], "reason": "无日期"}
    )
    assert review["ok"] is False
    assert review["missing"] == ["时间窗口"]
    notice = format_sql_review_notice(review)
    assert "不可作为最终事实" in notice
    assert "时间窗口" in notice


def test_format_sql_review_notice_pass() -> None:
    notice = format_sql_review_notice({"ok": True, "uncertain": False, "missing": []})
    assert "可见" in notice
