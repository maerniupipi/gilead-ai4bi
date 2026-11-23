"""User-facing lab names. Internal lab_id (Bootcamp slot) stays unchanged."""

from __future__ import annotations

# Credential / ask_lab id → business display name for prompts and traces.
LAB_DISPLAY_NAMES: dict[str, str] = {
    "actual": "吉利德 DDI",
    "demand": "Demand",
    "ext_simple": "外部数据·简单",
    "ext_complex": "外部数据·复杂",
}


def lab_display_name(lab_id: str | None) -> str:
    clean = str(lab_id or "").strip()
    if not clean:
        return "（未指定）"
    return LAB_DISPLAY_NAMES.get(clean, clean)
