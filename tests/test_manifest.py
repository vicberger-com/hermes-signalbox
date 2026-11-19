"""Tests for the manifest schema and validator."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

import validate_manifest as vm

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "module" / "module.toml"


def _doc() -> dict[str, Any]:
    return copy.deepcopy(tomllib.loads(TEMPLATE.read_text(encoding="utf-8")))


def test_template_manifest_is_valid() -> None:
    assert vm.validate_file(TEMPLATE) == []


def test_unknown_key_is_rejected() -> None:
    doc = _doc()
    doc["module"]["surprise"] = True
    assert any("unknown key 'surprise'" in e for e in vm.validate_document(doc))


def test_unknown_capability_is_rejected() -> None:
    doc = _doc()
    doc["capabilities"]["request"].append("root.everything")
    assert any("root.everything" in e for e in vm.validate_document(doc))


def test_missing_required_section_is_rejected() -> None:
    doc = _doc()
    del doc["lifecycle"]
    assert any("missing required key 'lifecycle'" in e for e in vm.validate_document(doc))


def test_net_capability_needs_declared_hosts() -> None:
    doc = _doc()
    doc["capabilities"]["request"].append("net.outbound")
    assert any("net.outbound" in e for e in vm.validate_document(doc))
    doc["capabilities"]["net_hosts"] = ["api.example.com"]
    assert vm.validate_document(doc) == []


def test_hosts_without_capability_are_rejected() -> None:
    doc = _doc()
    doc["capabilities"]["net_hosts"] = ["api.example.com"]
    assert any("net.outbound" in e for e in vm.validate_document(doc))


def test_secret_names_need_capability() -> None:
    doc = _doc()
    doc["capabilities"]["secrets"] = ["provider.key"]
    assert any("secrets.read" in e for e in vm.validate_document(doc))


def test_proprietary_connector_must_be_isolated() -> None:
    doc = _doc()
    doc["module"]["license_class"] = "proprietary-connector"
    assert any("subprocess" in e for e in vm.validate_document(doc))
    doc["module"]["isolation"] = "subprocess"
    assert vm.validate_document(doc) == []


def test_git_update_needs_pinned_commit() -> None:
    doc = _doc()
    doc["update"] = {"source": "git", "url": "https://github.com/example/mod", "ref": "main"}
    assert any("ref" in e for e in vm.validate_document(doc))
    doc["update"]["ref"] = "0123456789abcdef0123456789abcdef01234567"
    assert vm.validate_document(doc) == []


def test_idle_stop_requires_auto_activation() -> None:
    doc = _doc()
    doc["lifecycle"] = {"activation": "manual", "idle_stop_seconds": 60}
    assert any("idle_stop_seconds" in e for e in vm.validate_document(doc))


def test_schema_version_must_be_one() -> None:
    doc = _doc()
    doc["schema"] = 2
    assert any("$.schema" in e for e in vm.validate_document(doc))


def test_validator_refuses_unsupported_schema_keyword() -> None:
    try:
        vm.check("x", {"type": "string", "maxLength": 3})
    except ValueError as exc:
        assert "maxLength" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_invalid_toml_reports_one_error(tmp_path: Path) -> None:
    bad = tmp_path / "module.toml"
    bad.write_text("schema = = 1", encoding="utf-8")
    errors = vm.validate_file(bad)
    assert len(errors) == 1 and "cannot read manifest" in errors[0]


def test_cli_searches_directories_and_fails_on_empty_ones(tmp_path: Path) -> None:
    assert vm.main([str(ROOT / "templates")]) == 0
    assert vm.main([str(tmp_path)]) == 1
