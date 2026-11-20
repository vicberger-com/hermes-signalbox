"""M5 activation: config broker (backup, audit, read-back, rollback, revert), presets, benchmark, TTL."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from switchyard.contract import run_contract
from switchyard.core import BUILTIN_MODULES, Core
from switchyard.errors import SwitchyardError
from switchyard.hermesconfig import ConfigWriter

pytestmark = pytest.mark.bundled_modules
MODULE_DIR = Path(BUILTIN_MODULES) / "activation"
ESSENTIAL = {"hermes-agent"}

SKILLS = [
    {"name": "hermes-agent", "category": "", "description": "Hermes itself " * 5},
    {"name": "github", "category": "software-development", "description": "GitHub via gh CLI " * 4},
    {"name": "codebase-inspection", "category": "software-development", "description": "Inspect code " * 3},
    {"name": "arxiv", "category": "research", "description": "Search arXiv papers " * 6},
    {"name": "manim-video", "category": "creative", "description": "Manim animations " * 8},
    {"name": "p5js", "category": "creative", "description": "p5.js sketches " * 8},
    {"name": "bad name!", "category": "x", "description": "dropped"},
]


class FakeHermesConfig:
    """Stands in for Hermes's config.yaml. Like Hermes, it silently drops essential skills from the list."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {"skills.disabled": ["p5js"]}
        self.fail_next = False
        self.corrupt_next = False
        self.writes = 0

    def get(self, key: str) -> Any:
        return self.values.get(key)

    def set(self, key: str, value: Any) -> None:
        self.writes += 1
        if self.fail_next:
            self.fail_next = False
            self.values[key] = ["half-written"]
            raise OSError("disk full")
        if self.corrupt_next:
            self.corrupt_next = False
            self.values[key] = [*value, "surprise"]
            return
        self.values[key] = [v for v in value if v not in ESSENTIAL]

    def skills(self) -> list[dict[str, str]]:
        return [dict(s) for s in SKILLS]


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def act(core: Core, action: str, actor: str = "t", **args: Any) -> Any:
    return core.run("module", "action", {"id": "activation", "action": action, "args": args}, actor=actor)


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def port() -> FakeHermesConfig:
    return FakeHermesConfig()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def core(tmp_path: Path, port: FakeHermesConfig, clock: Clock) -> Iterator[Core]:
    c = Core(data_dir=tmp_path / "data", hosting=True, hermes_config=port)
    for cap in ("hermes.config.write", "hermes.hooks", "ui.panel"):
        c.run("module", "grant", {"id": "activation", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "activation"}, actor="t")
    c.manager._entry("activation").instance.clock = clock
    yield c
    c.close()


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_writer_backs_up_audits_verifies_and_rolls_back(tmp_path: Path, port: FakeHermesConfig) -> None:
    records: list[dict[str, Any]] = []

    class Sink:
        def append(self, **kw: Any) -> None:
            records.append(kw)

    w = ConfigWriter(port, Sink(), tmp_path / "backups")  # type: ignore[arg-type]
    out = w.set("m", "skills.disabled", ["arxiv", "hermes-agent", "arxiv"], actor="t")
    assert out["stored"] == ["arxiv"] and out["refused"] == ["hermes-agent"]
    backup = json.loads((tmp_path / "backups" / f"{out['backup']}.json").read_text(encoding="utf-8"))
    assert backup["old"] == ["p5js"] and backup["new"] == ["arxiv", "hermes-agent"]
    assert records[-1]["action"] == "hermes.config.write"
    port.fail_next = True
    with pytest.raises(SwitchyardError, match="previous value restored"):
        w.set("m", "skills.disabled", ["github"], actor="t")
    assert port.values["skills.disabled"] == ["arxiv"] and records[-1]["action"] == "hermes.config.rollback"
    port.corrupt_next = True
    with pytest.raises(SwitchyardError, match=r"failed \(SwitchyardError\); previous value restored"):
        w.set("m", "skills.disabled", ["github"], actor="t")
    assert port.values["skills.disabled"] == ["arxiv"]
    w.revert("m", out["backup"], actor="t")
    assert port.values["skills.disabled"] == ["p5js"]
    for key, value in [
        ("model.default", ["x"]),
        ("skills.disabled", "github"),
        ("skills.disabled", ["bad name"]),
        ("skills.disabled", [3]),
    ]:
        with pytest.raises(SwitchyardError):
            w.set("m", key, value, actor="t")
    for bad in ("../../etc", "20261120000000000000-zzzzzzzz", "20261120000000000000-00000000"):
        with pytest.raises(SwitchyardError):
            w.revert("m", bad, actor="t")
    assert len(w.backups(50)) == 4
    (tmp_path / "backups" / "20261120000000000000-0000000a.json").write_text("not json", encoding="utf-8")
    assert len(w.backups(50)) == 4
    port.values["skills.disabled"] = "single"
    assert w.get("skills.disabled") == ["single"]


def test_inventory_and_benchmark_measure_prompt_reduction(core: Core) -> None:
    inv = act(core, "inventory", actor="hermes")
    assert inv["count"] == 6 and next(s for s in inv["skills"] if s["name"] == "p5js")["enabled"] is False
    act(
        core,
        "preset_add",
        name="coding",
        enable="category:software-development",
        disable="category:creative,category:research",
        description="coding work",
    )
    act(core, "preset_add", name="idle", disable="*")
    bench = act(core, "benchmark", actor="hermes", name="coding")
    expected_after = inv["enabled_tokens"] - sum(
        s["tokens"] for s in inv["skills"] if s["name"] in {"arxiv", "manim-video"}
    )
    assert bench["before_tokens"] == inv["enabled_tokens"] and bench["after_tokens"] == expected_after
    assert bench["reduction_percent"] > 40
    idle = act(core, "benchmark", name="idle")
    assert (
        idle["after_tokens"] == 0
    )  # the benchmark counts what is asked; Hermes keeps essential skills anyway
    assert [p["name"] for p in act(core, "presets")["presets"]] == ["coding", "idle"]


def test_apply_restore_and_undo(core: Core, port: FakeHermesConfig) -> None:
    act(core, "preset_add", name="coding", enable="p5js", disable="category:research,manim-video")
    out = act(core, "apply", name="coding")
    assert port.values["skills.disabled"] == ["arxiv", "manim-video"] and out["refused"] == []
    act(core, "preset_add", name="idle", disable="*")
    second = act(core, "apply", name="idle")
    assert "hermes-agent" in second["refused"] and second["baseline"] == out["baseline"]
    assert act(core, "restore")["restored"] == out["backup"]
    assert port.values["skills.disabled"] == ["p5js"]
    with pytest.raises(SwitchyardError, match="no preset is active"):
        act(core, "restore")
    act(core, "undo", backup=second["backup"])  # back to the 'coding' state
    assert port.values["skills.disabled"] == ["arxiv", "manim-video"]
    history = act(core, "history", n=10)["backups"]
    assert len(history) == 4 and history[0]["note"] == f"revert of {second['backup']}"  # newest first
    actions = [r["action"] for r in core.run("audit", "tail", {"n": 100}, actor="t")]
    assert actions.count("hermes.config.write") == 4


def test_ttl_restores_previous_state(core: Core, port: FakeHermesConfig, clock: Clock) -> None:
    act(core, "preset_add", name="research", enable="arxiv,p5js")
    act(core, "apply", name="research", ttl_minutes=30)
    assert port.values["skills.disabled"] == []
    core.bridge.dispatch_hook("pre_llm_call", {"turn_id": "t"})
    assert port.values["skills.disabled"] == []  # not yet
    clock.now += 31 * 60
    core.bridge.dispatch_hook("pre_llm_call", {"turn_id": "t2"})
    assert port.values["skills.disabled"] == ["p5js"]
    assert (
        core.run("module", "panel", {"id": "activation", "panel": "activation.status"}, actor="t")["active"]
        is None
    )
    act(core, "apply", name="research", ttl_minutes=1)
    clock.now += 120
    assert core.manager._entry("activation").instance.health()[1] == "no preset active"


def test_model_is_read_only_and_bad_inputs(core: Core, port: FakeHermesConfig) -> None:
    act(core, "preset_add", name="coding", disable="arxiv")
    for action, args in [
        ("apply", {"name": "coding"}),
        ("preset_add", {"name": "x", "disable": "*"}),
        ("restore", {}),
        ("undo", {"backup": "x"}),
        ("preset_remove", {"name": "coding"}),
    ]:
        with pytest.raises(SwitchyardError, match="read-only"):
            act(core, action, actor="hermes", **args)
    assert port.writes == 0
    bad = [
        ("preset_add", {"name": "Bad Name", "disable": "a"}),
        ("preset_add", {"name": "x"}),
        ("preset_add", {"name": "x", "disable": "bad entry!"}),
        ("apply", {"name": "nope"}),
        ("apply", {"name": "coding", "ttl_minutes": -1}),
        ("history", {"n": 0}),
        ("benchmark", {"name": "nope"}),
        ("preset_remove", {"name": "nope"}),
        ("preset_add", {"name": "x", "disable": ",".join(f"s{i}" for i in range(501))}),
    ]
    for action, args in bad:
        with pytest.raises(SwitchyardError):
            act(core, action, **args)
    act(core, "preset_remove", name="coding")
    assert act(core, "presets")["presets"] == []


def test_without_a_hermes_config_port(tmp_path: Path) -> None:
    c = Core(data_dir=tmp_path / "d", hosting=True)
    try:
        for cap in ("hermes.config.write", "hermes.hooks", "ui.panel"):
            c.run("module", "grant", {"id": "activation", "capability": cap}, actor="t")
        c.run("module", "activate", {"id": "activation"}, actor="t")
        with pytest.raises(SwitchyardError, match="not available"):
            act(c, "inventory")
    finally:
        c.close()
    data = tmp_path / "d2"
    data.mkdir()
    (data / "config.toml").write_text("[modules.activation]\nx = 1\n", encoding="utf-8")
    c = Core(data_dir=data, hosting=True, hermes_config=FakeHermesConfig())
    try:
        for cap in ("hermes.config.write", "hermes.hooks", "ui.panel"):
            c.run("module", "grant", {"id": "activation", "capability": cap}, actor="t")
        c.run("module", "activate", {"id": "activation"}, actor="t")
        assert c.run("module", "show", {"id": "activation"}, actor="t")["status"] == "failed"
    finally:
        c.close()
