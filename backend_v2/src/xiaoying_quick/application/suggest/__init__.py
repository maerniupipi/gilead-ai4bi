"""Post-answer suggested questions (catalog-only; never an Agent loop tool)."""

from xiaoying_quick.application.suggest.service import build_suggestions, format_answer_data

__all__ = ["build_suggestions", "format_answer_data"]
