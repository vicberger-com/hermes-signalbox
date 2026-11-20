"""Core manifest loader (spec section 3, Manifest)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from switchyard.errors import ManifestError
from switchyard.manifest import MAX_MANIFEST_BYTES, check, load_manifest, load_schema

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "templates" / "module"


def _copy_template(tmp_path: Path) -> Path:
    target = tmp_path / "example"
    shutil.copytree(TEMPLATE_DIR, target, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    return target


def _rewrite(module_dir: Path, old: str, new: str) -> None:
    path = module_dir / "module.toml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_schema_ships_inside_the_package() -> None:
    schema = load_schema()
    assert schema["properties"]["schema"] == {"const": 1}


def test_template_loads_into_a_manifest() -> None:
    m = load_manifest(TEMPLATE_DIR / "module.toml")
    assert m.id == "example" and m.version == "0.1.0"
    assert m.requested == frozenset({"ui.panel"})
    assert m.entry_module == "example" and m.entry_class == "ExampleModule"
    assert m.isolation == "in-process" and m.activation == "manual" and m.idle_stop_seconds == 0
    assert m.contributes["panels"] == ("example.status",)
    assert m.directory == TEMPLATE_DIR
    assert m.entry_file == TEMPLATE_DIR / "example.py"
    assert m.update_source == "bundled" and m.update_ref is None


def test_loading_a_directory_finds_module_toml() -> None:
    assert load_manifest(TEMPLATE_DIR).id == "example"


def test_invalid_manifest_raises_with_all_errors(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    _rewrite(d, 'id = "example"', 'id = "Bad Id"\nsurprise = 1')
    with pytest.raises(ManifestError) as info:
        load_manifest(d)
    assert len(info.value.errors) == 2
    assert "module.toml" in str(info.value)


def test_entry_module_must_exist_inside_the_module(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    _rewrite(d, 'entry = "example:ExampleModule"', 'entry = "os:path"')
    with pytest.raises(ManifestError, match="entry module"):
        load_manifest(d)


def test_entry_with_empty_dotted_part_is_rejected(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    _rewrite(d, 'entry = "example:ExampleModule"', 'entry = "example..x:ExampleModule"')
    with pytest.raises(ManifestError, match="entry"):
        load_manifest(d)


def test_entry_package_resolves_to_init(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    pkg = d / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("class Mod: ...\n", encoding="utf-8")
    _rewrite(d, 'entry = "example:ExampleModule"', 'entry = "pkg:Mod"')
    assert load_manifest(d).entry_file == pkg / "__init__.py"


def test_entry_symlink_escaping_the_module_is_rejected(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("class Evil: ...\n", encoding="utf-8")
    (d / "example.py").unlink()
    try:
        os.symlink(outside, d / "example.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this host")
    with pytest.raises(ManifestError, match="outside"):
        load_manifest(d)


def test_oversize_manifest_is_refused(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    with (d / "module.toml").open("a", encoding="utf-8") as fh:
        fh.write("#" * MAX_MANIFEST_BYTES)
    with pytest.raises(ManifestError, match="too large"):
        load_manifest(d)


def test_missing_manifest_is_a_manifest_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="cannot read"):
        load_manifest(tmp_path)


def test_pattern_end_anchor_rejects_trailing_newline() -> None:
    # Python's `$` matches before a final newline; JSON Schema (ECMA-262) does not.
    assert check("abc\n", {"type": "string", "pattern": "^[a-z]+$"})
    assert check("abc", {"type": "string", "pattern": "^[a-z]+$"}) == []


def test_module_id_with_trailing_newline_is_rejected(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    _rewrite(d, 'id = "example"', 'id = "example\\n"')
    with pytest.raises(ManifestError, match="id"):
        load_manifest(d)


def test_module_id_with_double_underscore_is_rejected(tmp_path: Path) -> None:
    d = _copy_template(tmp_path)
    _rewrite(d, 'id = "example"', 'id = "ex__ample"')
    with pytest.raises(ManifestError, match="__"):
        load_manifest(d)
