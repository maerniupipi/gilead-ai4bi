import importlib.util
from pathlib import Path
from zipfile import ZipFile

_HELPER = Path(__file__).resolve().parents[2] / "tools" / "write_utf8_zip.py"
_SPEC = importlib.util.spec_from_file_location("write_utf8_zip", _HELPER)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
write_utf8_zip = _MODULE.write_utf8_zip


def test_non_ascii_names_set_the_utf8_language_encoding_flag(tmp_path: Path) -> None:
    source = tmp_path / "stage"
    target = source / "knowledge" / "项目知识文档"
    target.mkdir(parents=True)
    (target / "业务知识.md").write_text("# 业务知识\n", encoding="utf-8")
    (source / "seed-files").mkdir()
    (source / "seed-files" / "business.md").write_text("# 业务知识\n", encoding="utf-8")
    out = tmp_path / "app.zip"

    write_utf8_zip(source, out)

    with ZipFile(out) as archive:
        names = set(archive.namelist())
        chinese = "knowledge/项目知识文档/业务知识.md"
        ascii_copy = "seed-files/business.md"
        assert chinese in names
        assert ascii_copy in names
        assert archive.getinfo(chinese).flag_bits & 0x800
        assert archive.getinfo(ascii_copy).flag_bits & 0x800 == 0
