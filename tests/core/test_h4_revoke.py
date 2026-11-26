"""H4-N1: a capability revoked from another process stops the module in the hosting process.

Found while fixing R1-F9 (same cause): ``module revoke`` is an offline operation. In the process that runs it,
a module that needs the capability is stopped; but when another process hosts (the Hermes gateway), the host
kept the module active, with hooks, gates and jobs registered under the old grant, until it restarted. The
host's tick now stops an active module whose required grants are no longer complete.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sy_testing import write_module

from hermes_signalbox import cli
from hermes_signalbox.core import Core


@pytest.fixture(autouse=True)
def _no_env_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    write_module(root / "modules", "m2", isolation="subprocess", request=("ui.panel",))
    return root


@pytest.fixture
def host(data: Path) -> Iterator[Core]:
    core = Core(data_dir=data, hosting=True)
    core.run("module", "grant", {"id": "m2", "capability": "ui.panel"}, actor="cli")
    core.run("module", "activate", {"id": "m2"}, actor="cli")
    assert core.manager.info("m2").status.value == "active"
    yield core
    core.close()


def _cli(data: Path, *args: str) -> int:
    return cli.main(["--data-dir", str(data), *args])


def _deactivations(core: Core) -> list[dict[str, str]]:
    return [
        r["detail"]
        for r in core.audit_log.tail(200)
        if r["action"] == "module.deactivated" and r["module"] == "m2"
    ]


def test_h4_n1_revoke_from_cli_stops_the_module_in_the_host(data: Path, host: Core) -> None:
    assert _cli(data, "module", "revoke", "m2", "--capability", "ui.panel") == 0
    host.tick()
    info = host.manager.info("m2")
    assert info.status.value == "stopped" and info.stop_reason == "revoked ui.panel"
    assert _deactivations(host)[-1] == {"reason": "revoked ui.panel"}


def test_h4_n1_the_host_does_not_restart_it_on_its_own(data: Path, host: Core) -> None:
    assert _cli(data, "module", "revoke", "m2", "--capability", "ui.panel") == 0
    host.tick()
    host.manager.start_auto(actor="core")  # auto_skipped, not started: the grant is still missing
    host.tick()
    assert host.manager.info("m2").status.value == "stopped"


def test_h4_n1_a_complete_grant_set_leaves_the_module_running(host: Core) -> None:
    host.tick()
    host.tick()
    assert host.manager.info("m2").status.value == "active"
    assert _deactivations(host) == []


def test_h4_n1_revoking_an_optional_capability_keeps_the_module(tmp_path: Path) -> None:
    data = tmp_path / "opt"
    module = write_module(data / "modules", "m3", isolation="subprocess", request=("ui.panel",))
    toml = module / "module.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace(
            'request = ["ui.panel"]', 'request = ["ui.panel"]\noptional = ["ui.panel"]'
        ),
        encoding="utf-8",
    )
    with Core(data_dir=data, hosting=True) as host:
        host.run("module", "grant", {"id": "m3", "capability": "ui.panel"}, actor="cli")
        host.run("module", "activate", {"id": "m3"}, actor="cli")
        assert _cli(data, "module", "revoke", "m3", "--capability", "ui.panel") == 0
        host.tick()
        assert host.manager.info("m3").status.value == "active"  # optional: checked when used, as before


def test_h4_n1_revoke_in_the_hosting_process_still_stops_once(host: Core) -> None:
    result = host.run("module", "revoke", {"id": "m2", "capability": "ui.panel"}, actor="cli")
    assert result["deactivated"] is True
    host.tick()
    assert len(_deactivations(host)) == 1
