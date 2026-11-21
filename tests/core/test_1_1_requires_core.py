"""1.1 backlog: requires_core is enforced, with a 1.0 transition for the old template's "<1" (H1 A-20 #91).

Q-SY-1.1-3 (a): a module whose only mismatch is the old template's ``<1`` upper bound still loads, with an
audited ``module.requires_core_outdated`` warning and a note in ``module show``; any other mismatch refuses
the module. The transition ends at core 2.0.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sy_testing import ManifestFactory, RecordingAudit, write_module

import switchyard
from switchyard.errors import ManifestError
from switchyard.manifest import core_compatibility, load_manifest

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = ROOT / "src" / "switchyard" / "modules"


@pytest.mark.parametrize(
    ("spec", "core", "verdict"),
    [
        (">=1.0,<2", "1.0.1", "ok"),
        (">=1.0.1", "1.0.1", "ok"),
        ("==1.0.1", "1.0.1", "ok"),
        (">=0.1,<1", "1.0.1", "outdated"),  # the old template: loads, with a warning
        ("<1.0.0", "1.4.0", "outdated"),
        (">=0.1,<1", "2.0.0", "incompatible"),  # the transition ends at 2.0
        (">=1.2", "1.0.1", "incompatible"),  # needs a newer core
        (">=0.1,<0.9", "1.0.1", "incompatible"),  # not the template's bound
        (">=1.0,<2", "2.0.0", "incompatible"),
        (">=1.0,<2", "1.1.0-rc.1", "ok"),
    ],
)
def test_h1_a20_compatibility_verdicts(spec: str, core: str, verdict: str) -> None:
    assert core_compatibility(spec, core)[0] == verdict


@pytest.mark.parametrize("spec", ["banana", ">=1.0;<2", "~=1.0", ">=", ">=1.0,,<2", "1.0"])
def test_h1_a20_an_unreadable_spec_is_a_manifest_error(make_manifest: ManifestFactory, spec: str) -> None:
    with pytest.raises(ManifestError, match="requires_core"):
        make_manifest("demo", requires_core=spec)


def _manager(tmp_path: Path, audit: RecordingAudit):  # type: ignore[no-untyped-def]
    from switchyard.capabilities import MemoryGrantStore, PolicyEngine
    from switchyard.context import MemoryPanelRegistry
    from switchyard.events import EventBus
    from switchyard.lifecycle import ModuleManager
    from switchyard.logs import JsonlLogSink
    from switchyard.scheduler import Scheduler

    trusted = tmp_path / "trusted"
    trusted.mkdir()
    bus = EventBus(audit, clock=lambda: "t")
    manager = ModuleManager(
        policy=PolicyEngine(MemoryGrantStore(), audit), audit=audit, bus=bus,
        logs=JsonlLogSink(tmp_path / "logs"), panels=MemoryPanelRegistry(),
        scheduler=Scheduler(bus, audit, monotonic=lambda: 0.0), store=None, trusted_roots=[trusted],
        clock=lambda: 0.0,
    )  # fmt: skip
    return manager, trusted


def test_h1_a20_a_module_needing_a_newer_core_is_refused(tmp_path: Path, audit: RecordingAudit) -> None:
    manager, trusted = _manager(tmp_path, audit)
    write_module(trusted, "future", requires_core=">=9.0")
    assert manager.discover([trusted]) == []
    rejected = [r for r in audit.records if r["action"] == "module.rejected"]
    assert rejected and "requires core >=9.0" in rejected[-1]["detail"]["reason"]


def test_h1_a20_an_old_template_module_loads_with_a_warning(tmp_path: Path, audit: RecordingAudit) -> None:
    manager, trusted = _manager(tmp_path, audit)
    write_module(trusted, "legacy", requires_core=">=0.1,<1")
    write_module(trusted, "current")
    assert manager.discover([trusted]) == ["current", "legacy"]
    warned = [r for r in audit.records if r["action"] == "module.requires_core_outdated"]
    assert [r["module"] for r in warned] == ["legacy"]
    assert warned[0]["detail"]["requires_core"] == ">=0.1,<1"


@pytest.mark.bundled_modules
def test_h1_a20_module_show_carries_the_note(tmp_path: Path) -> None:
    from switchyard.core import Core

    data = tmp_path / "data"
    write_module(data / "modules", "legacy", requires_core=">=0.1,<1", isolation="subprocess")
    core = Core(data_dir=data)
    try:
        shown = core.run("module", "show", {"id": "legacy"}, actor="cli")
        assert shown["requires_core"] == ">=0.1,<1"
        assert "outdated" in shown["requires_core_note"]
        assert core.run("module", "show", {"id": "inbox"}, actor="cli")["requires_core_note"] == ""
    finally:
        core.close()


def test_h1_a20_bundled_modules_and_the_template_declare_the_1x_range() -> None:
    dirs = [d for d in BUNDLED.iterdir() if (d / "module.toml").is_file()]
    assert dirs
    for d in dirs:
        m = load_manifest(d)
        assert m.requires_core == ">=1.0,<2", d.name
        assert core_compatibility(m.requires_core, switchyard.__version__)[0] == "ok"
    assert 'requires_core = ">=1.0,<2"' in (ROOT / "templates" / "module" / "module.toml").read_text("utf-8")
