"""H1 WP5: activation rules (findings C-6, A-5) and unregistered persona models (C-7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sy_testing import write_module

from hermes_signalbox.core import Core
from hermes_signalbox.errors import CapabilityDenied

CODE = """
class Mod:
    def activate(self, ctx):
        import pathlib
        pathlib.Path(ctx.config.get("marker", "")).write_text("ran", encoding="utf-8")
    def deactivate(self):
        pass
    def health(self):
        return (True, "ok")
"""


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)


@pytest.fixture
def core(tmp_path: Path) -> Any:
    root = tmp_path / "modules"
    write_module(root, "man", CODE, request=("ui.panel",), activation="manual")
    write_module(root, "aut", CODE, request=("ui.panel",), activation="auto")
    data = tmp_path / "data"
    data.mkdir()
    marker = tmp_path / "ran.txt"
    line = f"marker = {json.dumps(str(marker))}\n"
    (data / "config.toml").write_text(f"[modules.man]\n{line}[modules.aut]\n{line}", encoding="utf-8")
    c = Core(data_dir=data, trusted_roots=[root], module_roots=[root], hosting=True)
    c.marker = marker  # type: ignore[attr-defined]
    yield c
    c.close()


def _denied(core: Core) -> list[dict[str, Any]]:
    return [r for r in core.run("audit", "tail", {"n": 50}, actor="t") if r["action"] == "policy.denied"]


def test_h1_a5_activation_needs_every_required_grant_and_runs_no_code(core: Core) -> None:
    with pytest.raises(CapabilityDenied, match=r"ui.panel"):
        core.run("module", "activate", {"id": "man"}, actor="t")
    assert not core.marker.exists()  # type: ignore[attr-defined]  # module code never ran
    assert core.run("module", "show", {"id": "man"}, actor="t")["status"] == "verified"  # not "failed"
    assert _denied(core)[-1]["detail"]["capability"] == "ui.panel"
    core.run("module", "grant", {"id": "man", "capability": "ui.panel"}, actor="t")
    assert core.run("module", "activate", {"id": "man"}, actor="t")["status"] == "active"
    assert core.marker.exists()  # type: ignore[attr-defined]


def test_h1_c6_model_may_activate_only_auto_modules(core: Core) -> None:
    for mid in ("man", "aut"):
        core.run("module", "grant", {"id": mid, "capability": "ui.panel"}, actor="t")
    with pytest.raises(CapabilityDenied, match="manual"):
        core.run("module", "activate", {"id": "man"}, actor="hermes")
    record = _denied(core)[-1]
    assert record["module"] == "man" and record["detail"]["reason"] == "mode manual"
    assert core.run("module", "show", {"id": "man"}, actor="t")["status"] == "verified"
    assert core.run("module", "activate", {"id": "aut"}, actor="hermes")["status"] == "active"
    core.run("module", "mode", {"id": "man", "mode": "auto"}, actor="t")
    assert core.run("module", "activate", {"id": "man"}, actor="hermes")["status"] == "active"


def test_h1_c6_tool_description_says_auto_only() -> None:
    from hermes_signalbox.hermes import MODULES_SCHEMA

    assert "auto" in MODULES_SCHEMA["description"]
