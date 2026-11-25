"""H4 WP5: command-line polish found in the v1.0.2 acceptance install.

- R1-F4: granting a capability to an unknown module is a usage error (exit 2), as REFERENCE's exit-code table
  says for an unknown name; it was refused as a policy denial (exit 3).
- R1-F5: a live command run while another process hosts the data directory without the API names the steps
  that work for that setup (``[api] enabled = true`` plus a restart, or ``/switchyard`` in a chat) instead
  of telling the operator to start ``switchyard api serve``, which cannot start while the directory is hosted.
- R1-F7: setting the mode a module already has records no ``module.mode_changed``.
- R1-F12: the usage report says why a module's section is missing (``not installed``, ``not active``) instead
  of printing an exception class name.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sy_testing import write_module

from switchyard import cli
from switchyard.core import Core
from switchyard.errors import CapabilityDenied, UsageError

USAGE_MODULES = ("meter", "router", "trimmer", "workers")


@pytest.fixture(autouse=True)
def _no_env_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    write_module(root / "modules", "m1", isolation="subprocess", request=("ui.panel",))
    return root


@pytest.fixture
def core(data: Path) -> Iterator[Core]:
    c = Core(data_dir=data, hosting=True)
    yield c
    c.close()


def _cli(data: Path, *args: str) -> int:
    return cli.main(["--data-dir", str(data), *args])


def _actions(core: Core, action: str, module: str) -> list[dict[str, str]]:
    return [r["detail"] for r in core.audit_log.tail(500) if r["action"] == action and r["module"] == module]


# R1-F4 ----------------------------------------------------------------------------------------------------


def test_h4_r1_f4_grant_to_unknown_module_exits_2(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _cli(data, "module", "grant", "nosuch", "--capability", "ui.panel") == 2
    err = capsys.readouterr().err
    assert err.startswith("error:") and "unknown module 'nosuch'" in err


def test_h4_r1_f4_grant_to_unknown_module_is_a_usage_error_and_still_audited(core: Core) -> None:
    with pytest.raises(UsageError) as info:
        core.run("module", "grant", {"id": "nosuch", "capability": "ui.panel"}, actor="cli")
    assert not isinstance(info.value, CapabilityDenied)
    assert _actions(core, "policy.grant_refused", "nosuch")[-1] == {
        "capability": "ui.panel",
        "reason": "module not registered",
    }


def test_h4_r1_f4_real_denials_keep_exit_3(data: Path) -> None:
    # guard: a capability the manifest does not request is still a policy refusal
    assert _cli(data, "module", "grant", "m1", "--capability", "net.outbound") == 3


# R1-F5 ----------------------------------------------------------------------------------------------------


def test_h4_r1_f5_live_command_while_hosted_without_api_names_the_hosted_setup(
    data: Path, core: Core, capsys: pytest.CaptureFixture[str]
) -> None:
    assert core.hosting and not (data / "api.port").exists()
    assert _cli(data, "module", "activate", "m1") == 1
    err = capsys.readouterr().err
    assert "api serve" not in err
    assert "[api] enabled = true" in err and "restart" in err
    assert "/switchyard module activate m1" in err


def test_h4_r1_f5_live_command_with_nobody_hosting_still_names_api_serve(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # guard: with no hosting process, starting the daemon is the right step
    assert _cli(data, "module", "activate", "m1") == 1
    assert "switchyard api serve" in capsys.readouterr().err


# R1-F7 ----------------------------------------------------------------------------------------------------


def test_h4_r1_f7_setting_the_current_mode_records_nothing(core: Core) -> None:
    core.run("module", "mode", {"id": "m1", "mode": "auto"}, actor="cli")
    core.run("module", "mode", {"id": "m1", "mode": "auto"}, actor="cli")
    assert _actions(core, "module.mode_changed", "m1") == [{"mode": "auto"}]
    core.run("module", "mode", {"id": "m1", "mode": "manual"}, actor="cli")
    assert _actions(core, "module.mode_changed", "m1") == [{"mode": "auto"}, {"mode": "manual"}]


def test_h4_r1_f7_initial_mode_again_records_nothing(core: Core) -> None:
    assert core.manager.info("m1").mode == "manual"
    result = core.run("module", "mode", {"id": "m1", "mode": "manual"}, actor="cli")
    assert result["mode"] == "manual"
    assert _actions(core, "module.mode_changed", "m1") == []


def test_h4_r1_f7_disabled_again_still_stops_an_active_module(core: Core) -> None:
    # guard: a module active under a stored "disabled" (another process set it, the tick has not run yet)
    # is still stopped when the operator says "disabled" here
    core.run("module", "grant", {"id": "m1", "capability": "ui.panel"}, actor="cli")
    core.run("module", "activate", {"id": "m1"}, actor="cli")
    core.store.core_execute("UPDATE modules SET mode = 'disabled' WHERE id = ?", ("m1",))
    core.run("module", "mode", {"id": "m1", "mode": "disabled"}, actor="cli")
    assert core.manager.info("m1").status.value == "stopped"


# R1-F12 ---------------------------------------------------------------------------------------------------


def _class_names(section: object) -> bool:
    text = str(section)
    return any(name in text for name in ("UsageError", "SwitchyardError", "ModuleNotRunning", "Error'"))


def test_h4_r1_f12_usage_report_says_not_installed(core: Core) -> None:
    # bundled modules are hidden in this test, so none of the usage modules exists
    usage = core.run("report", "show", {"kind": "usage"}, actor="cli")
    for module in USAGE_MODULES:
        assert usage[module] == {"unavailable": "not installed"}, module


@pytest.mark.bundled_modules
def test_h4_r1_f12_usage_report_says_not_active(core: Core) -> None:
    usage = core.run("report", "show", {"kind": "usage"}, actor="cli")
    for module in USAGE_MODULES:
        assert usage[module] == {"unavailable": "not active"}, module
        assert not _class_names(usage[module])
