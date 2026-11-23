"""Write a ZIP that marks non-ASCII names as UTF-8.

macOS ``zip`` stores Chinese filenames without the language encoding flag
(bit 11). Java unzip on SAE then mangles ``项目知识文档/业务知识.md``, the
knowledge seeder skips every file, and the published-knowledge page is empty.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

_SKIP_DIR_NAMES = {"__pycache__"}
_SKIP_FILE_NAMES = {".DS_Store"}


def write_utf8_zip(source_dir: Path, out: Path) -> None:
    source_dir = source_dir.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if _skip(path):
                continue
            archive.write(path, path.relative_to(source_dir).as_posix())


def _skip(path: Path) -> bool:
    if any(part in _SKIP_DIR_NAMES for part in path.parts):
        return True
    return path.name in _SKIP_FILE_NAMES


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: write_utf8_zip.py SOURCE_DIR OUT.zip")
    write_utf8_zip(Path(sys.argv[1]), Path(sys.argv[2]))
