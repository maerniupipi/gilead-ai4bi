"""SAE ZIP entry for the Xiaoying Quick API.

The packaged layout is::

    requirements.txt
    start.sh
    knowledge/
    app/
      main.py
      __main__.py
      xiaoying_quick/

This matches Aliyun SAE's Python ZIP convention: ``requirements.txt`` at the
ZIP root, application code under ``app/``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
_ZIP_ROOT = _APP_DIR.parent
for _candidate in (_APP_DIR, _ZIP_ROOT):
    _path = str(_candidate)
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _apply_runtime_defaults() -> None:
    for path in (
        _ZIP_ROOT / ".env",
        _ZIP_ROOT / "runtime.env",
        _APP_DIR / ".env",
        _APP_DIR / "runtime.env",
    ):
        _load_env_file(path)
    try:
        from runtime_defaults import SAE_RUNTIME_DEFAULTS
    except ImportError:
        SAE_RUNTIME_DEFAULTS = {}
    # Packaged UAT values are the source of truth. Leftover SAE console
    # variables must not hide Lab tokens or the database URL.
    for key, value in SAE_RUNTIME_DEFAULTS.items():
        os.environ[key] = value


def _default_knowledge_root() -> Path:
    configured = os.environ.get("XIAOYING_KNOWLEDGE_ROOT", "").strip()
    if configured:
        return Path(configured)
    for candidate in (_ZIP_ROOT / "knowledge", _APP_DIR / "knowledge"):
        if candidate.exists():
            return candidate
    return _ZIP_ROOT / "knowledge"


_apply_runtime_defaults()
(_ZIP_ROOT / "var").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XIAOYING_KNOWLEDGE_ROOT", str(_default_knowledge_root()))
os.environ.setdefault("XIAOYING_SECRET_STORE_PATH", str(_ZIP_ROOT / "var" / "secrets.json"))
os.environ.setdefault("XIAOYING_SECRET_KEY_PATH", str(_ZIP_ROOT / "var" / "master.key"))
if (_APP_DIR / "www" / "index.html").is_file():
    os.environ.setdefault("XIAOYING_STATIC_ROOT", str(_APP_DIR / "www"))

from xiaoying_quick.app import app  # noqa: E402

__all__ = ["app"]
