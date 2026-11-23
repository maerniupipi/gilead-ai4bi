from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "xiaoying_quick"
LOCKED = (
    "安达唐",
    "京东",
    "Forxiga",
    "AIA",
    "CHPA",
    "NIAD",
    "index_routing",
    "choices_for_slot",
    "required_query_slots",
    "_REWRITE_MARKERS",
    "_PRODUCTS",
    "_ACTUAL_CUES",
    "四个数据域",
)


def test_engine_source_has_no_locked_business_tokens() -> None:
    violations: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in LOCKED:
            if token in text:
                violations.append(f"{path}: {token}")
    assert violations == []


def test_index_routing_module_is_gone() -> None:
    assert not (PACKAGE / "modules" / "conversation" / "index_routing.py").exists()
