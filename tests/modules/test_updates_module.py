"""M12 scheduled update checks: announce once, never apply, model read-only."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sy_testing import GOOD, write_module

from hermes_signalbox.contract import run_contract
from hermes_signalbox.core import BUILTIN_MODULES, Core
from hermes_signalbox.errors import ChannelNotFound, SignalboxError, UpdateError

pytestmark = pytest.mark.bundled_modules
MODULE_DIR = Path(BUILTIN_MODULES) / "updates"
URL = "https://example.invalid/vendor/ext.git"
OLD, NEW = "1" * 40, "2" * 40


class Heads:
    def __init__(self) -> None:
        self.heads: dict[tuple[str, str], str] = {}

    def fetch(self, url: str, ref: str, dest: Path) -> None:
        raise UpdateError("not in this test")

    def latest(self, url: str, channel: str) -> str:
        if (url, channel) not in self.heads:
            raise ChannelNotFound("channel not found")
        return self.heads[(url, channel)]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes"))


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[tuple[Core, Heads]]:
    data = tmp_path / "data"
    src = write_module(tmp_path / "src", "ext", GOOD, isolation="subprocess")
    toml = src / "module.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + f'[update]\nsource = "git"\nurl = "{URL}"\nref = "{OLD}"\n'
        'channel = "stable"\n',
        encoding="utf-8",
    )
    (data / "modules").mkdir(parents=True)
    shutil.copytree(src, data / "modules" / "ext")
    (data / "config.toml").write_text("[modules.updates]\ninterval_hours = 24\n", encoding="utf-8")
    heads = Heads()
    core = Core(data_dir=data, fetcher=heads, hosting=True)
    for cap in ("schedule", "core.read", "notify", "ui.panel"):
        core.run("module", "grant", {"id": "updates", "capability": cap}, actor="t")
    core.run("module", "activate", {"id": "updates"}, actor="t")
    yield core, heads
    core.close()


def act(core: Core, name: str, actor: str = "t") -> Any:
    return core.run("module", "action", {"id": "updates", "action": name, "args": {}}, actor=actor)


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_announces_each_available_commit_once(
    setup: tuple[Core, Heads], monkeypatch: pytest.MonkeyPatch
) -> None:
    core, heads = setup
    monkeypatch.setattr("hermes_signalbox.updates.CHECK_MIN_SECONDS", 0.0)
    assert act(core, "check_now") == {"modules": 1, "available": 0, "errors": 1}
    heads.heads[(URL, "stable")] = NEW
    assert act(core, "check_now") == {"modules": 1, "available": 1, "errors": 0}
    assert act(core, "check_now")["available"] == 1
    alerts = [r for r in core.run("audit", "tail", {"n": 60}, actor="t") if r["action"] == "module.notify"]
    assert len(alerts) == 1
    report = act(core, "report", actor="hermes")
    assert report["modules"][0]["available"] == NEW and report["checked_at"]
    assert core.run("module", "show", {"id": "ext"}, actor="t")["version"] == "0.1.0"  # never applied


def test_rights_and_settings(setup: tuple[Core, Heads], tmp_path: Path) -> None:
    core, _ = setup
    with pytest.raises(SignalboxError, match="read-only"):
        act(core, "check_now", actor="hermes")
    for i, bad in enumerate(("interval_hours = 0", "interval_hours = true", "other = 1")):
        data = tmp_path / f"b{i}"
        data.mkdir()
        (data / "config.toml").write_text(f"[modules.updates]\n{bad}\n", encoding="utf-8")
        c = Core(data_dir=data, hosting=True)
        try:
            for cap in ("schedule", "core.read", "notify", "ui.panel"):
                c.run("module", "grant", {"id": "updates", "capability": cap}, actor="t")
            c.run("module", "activate", {"id": "updates"}, actor="t")
            assert c.run("module", "show", {"id": "updates"}, actor="t")["status"] == "failed"
        finally:
            c.close()
