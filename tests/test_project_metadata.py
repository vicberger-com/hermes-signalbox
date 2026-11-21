"""H1 WP10: project metadata agrees with itself (D-14, D-16, D-17, D-19) and the shared module helpers."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

import switchyard
from switchyard.errors import SwitchyardError
from switchyard.modkit import default_models_dev_cache, int_setting
from switchyard.ops import OPERATIONS

ROOT = Path(__file__).resolve().parents[1]


def _project() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]  # type: ignore[no-any-return]


def test_h1_d17_every_version_field_agrees() -> None:
    version = str(_project()["version"])
    plugin = re.search(r"^version:\s*(\S+)", (ROOT / "plugin.yaml").read_text(encoding="utf-8"), re.M)
    dashboard = json.loads((ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))["version"]
    released = re.search(
        r"^## \[(\d+\.\d+\.\d+)\]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M
    )
    assert plugin is not None and released is not None
    assert {switchyard.__version__, plugin.group(1), dashboard, released.group(1)} == {version}


def test_h1_d14_status_is_beta() -> None:
    classifiers = [str(c) for c in _project()["classifiers"]]  # type: ignore[attr-defined]
    assert "Development Status :: 4 - Beta" in classifiers
    assert not any("Production/Stable" in c for c in classifiers)


def test_h1_d16_tool_versions_agree() -> None:
    pre = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    ruff = re.search(r"^ruff==(\S+)", (ROOT / "requirements-dev.txt").read_text(encoding="utf-8"), re.M)
    leaks = re.search(
        r'GITLEAKS_VERSION:\s*"([^"]+)"',
        (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8"),
    )
    assert ruff is not None and leaks is not None
    assert f"frozen: v{ruff.group(1)}" in pre and f"frozen: v{leaks.group(1)}" in pre
    assert "P0 task" not in pre


def test_h1_d19_reference_lists_every_operation_and_global_option() -> None:
    text = (ROOT / "docs" / "REFERENCE.md").read_text(encoding="utf-8")
    assert "Generated from the code" not in text
    missing = [f"{n} {v}" for n, v in OPERATIONS if f"`{n} {v}" not in text]
    assert not missing
    for needle in (
        "`--json`",
        "`--data-dir PATH`",
        "`backup/`",
        "`trigger.fired`",
        "`verified`",
        "`disabled`",
    ):
        assert needle in text, needle


def test_h1_d18_no_stale_audit_at_the_root() -> None:
    assert not (ROOT / "docs_gap_audit.md").exists()


def test_h1_c13_shared_helpers() -> None:
    assert int_setting("demo", {"n": 5}, "n", 1, 1, 10) == 5
    assert int_setting("demo", {}, "n", 3, 1, 10) == 3
    for bad in (True, 0, 11, "5", 2.0):
        with pytest.raises(SwitchyardError, match=r"\[modules\.demo\] n must be an integer from 1 to 10"):
            int_setting("demo", {"n": bad}, "n", 1, 1, 10)
    assert default_models_dev_cache().name == "models_dev_cache.json"


def test_h1_c13_cache_location(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert default_models_dev_cache() == tmp_path / "models_dev_cache.json"
    monkeypatch.delenv("HERMES_HOME")
    monkeypatch.setattr("sys.platform", "linux")
    assert default_models_dev_cache() == Path.home() / ".hermes" / "models_dev_cache.json"
