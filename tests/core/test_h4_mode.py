"""H4 R1-F9: a module's mode set from another process reaches the hosting process and stays set.

The hosting process reads a module's mode from the state store before it acts on it, as it already does for
grants. Discovery in a process that does not host never rewrites the ``state`` column, and a change of mode
writes only the ``mode`` column. Removing a module that another process hosts is refused offline.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from sy_testing import write_module

from switchyard import cli
from switchyard.core import Core
from switchyard.errors import CapabilityDenied, ModuleNotRunning
from switchyard.ops import MODEL_ACTOR


@pytest.fixture(autouse=True)
def _no_env_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """A data directory with one ``manual`` module that needs no grant (the API stays off)."""
    root = tmp_path / "data"
    write_module(root / "modules", "m1", isolation="subprocess", activation="manual")
    return root


@pytest.fixture
def host(data: Path) -> Iterator[Core]:
    core = Core(data_dir=data, hosting=True)
    assert core.hosting
    yield core
    core.close()


def _cli(data: Path, *args: str) -> int:
    return cli.main(["--data-dir", str(data), *args])


def _row(data: Path, module_id: str) -> tuple[str, str]:
    """(mode, state) of a module as the state store has it, read without the core."""
    conn = sqlite3.connect(f"file:{(data / 'state.db').as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT mode, state FROM modules WHERE id = ?", (module_id,)).fetchall()
    finally:
        conn.close()
    assert rows, f"no modules row for {module_id}"
    return str(rows[0][0]), str(rows[0][1])


def _show(core: Core, module_id: str) -> dict[str, object]:
    result = core.run("module", "show", {"id": module_id}, actor="cli")
    assert isinstance(result, dict)
    return result


# T6: the host sees the mode another process set, and does not overwrite it ------------------------------


def test_h4_r1_f9_mode_set_from_cli_is_what_the_host_shows(data: Path, host: Core) -> None:
    assert _cli(data, "module", "mode", "m1", "--mode", "auto") == 0
    assert _row(data, "m1")[0] == "auto"
    assert _show(host, "m1")["mode"] == "auto"


def test_h4_r1_f9_host_activation_keeps_the_mode_set_from_cli(data: Path, host: Core) -> None:
    assert _cli(data, "module", "mode", "m1", "--mode", "auto") == 0
    host.run("module", "activate", {"id": "m1"}, actor="cli")
    assert _row(data, "m1") == ("auto", "active")
    host.run("module", "deactivate", {"id": "m1"}, actor="cli")
    assert _row(data, "m1") == ("auto", "stopped")


# T7: what the model may start follows the mode set elsewhere ---------------------------------------------


def test_h4_r1_f9_model_activate_follows_the_mode_set_from_cli(data: Path, host: Core) -> None:
    with pytest.raises(CapabilityDenied):
        host.run("module", "activate", {"id": "m1"}, actor=MODEL_ACTOR)
    assert _cli(data, "module", "mode", "m1", "--mode", "auto") == 0
    host.run("module", "activate", {"id": "m1"}, actor=MODEL_ACTOR)
    assert _show(host, "m1")["status"] == "active"
    host.run("module", "deactivate", {"id": "m1"}, actor="cli")
    assert _cli(data, "module", "mode", "m1", "--mode", "manual") == 0
    with pytest.raises(CapabilityDenied):
        host.run("module", "activate", {"id": "m1"}, actor=MODEL_ACTOR)


def test_h4_r1_f9_disabled_from_cli_stops_the_module_in_the_host(data: Path, host: Core) -> None:
    host.run("module", "activate", {"id": "m1"}, actor="cli")
    assert _cli(data, "module", "mode", "m1", "--mode", "disabled") == 0
    host.tick()
    info = host.manager.info("m1")
    assert info.status.value == "stopped" and info.stop_reason == "disabled"
    assert _row(data, "m1") == ("disabled", "stopped")
    with pytest.raises(ModuleNotRunning):
        host.run("module", "activate", {"id": "m1"}, actor="cli")


def test_h4_r1_f9_the_host_refuses_to_start_a_module_disabled_elsewhere(data: Path, host: Core) -> None:
    assert _cli(data, "module", "mode", "m1", "--mode", "disabled") == 0
    with pytest.raises(ModuleNotRunning):  # no tick in between: the activation itself reads the mode
        host.run("module", "activate", {"id": "m1"}, actor="cli")


def test_h4_r1_f9_auto_set_from_cli_is_started_by_start_auto(data: Path, host: Core) -> None:
    assert _cli(data, "module", "mode", "m1", "--mode", "auto") == 0
    host.manager.start_auto(actor="core")
    assert host.manager.info("m1").status.value == "active"


# T8: a process that does not host leaves the state column alone -----------------------------------------


def test_h4_r1_f9_cli_discovery_leaves_the_state_column_of_a_host_active_module(
    data: Path, host: Core
) -> None:
    host.run("module", "activate", {"id": "m1"}, actor="cli")
    assert _row(data, "m1")[1] == "active"
    assert _cli(data, "module", "list") == 0
    assert _row(data, "m1")[1] == "active"


def test_h4_r1_f9_mode_change_from_cli_writes_only_the_mode_column(data: Path, host: Core) -> None:
    host.run("module", "activate", {"id": "m1"}, actor="cli")
    assert _cli(data, "module", "mode", "m1", "--mode", "auto") == 0
    assert _row(data, "m1") == ("auto", "active")


def test_h4_r1_f9_a_new_host_writes_the_state_of_every_module(data: Path) -> None:
    with Core(data_dir=data, hosting=False):
        pass  # creates the row
    conn = sqlite3.connect(data / "state.db")
    try:  # a host that died while m1 ran left this behind
        conn.execute("UPDATE modules SET state = 'active' WHERE id = 'm1'")
        conn.commit()
    finally:
        conn.close()
    with Core(data_dir=data, hosting=True) as core:
        assert core.hosting
        assert _row(data, "m1")[1] == "verified"


def test_h4_r1_f9_a_late_host_writes_the_state_of_every_module(data: Path) -> None:
    with Core(data_dir=data, hosting=False) as late:
        conn = sqlite3.connect(data / "state.db")
        try:
            conn.execute("UPDATE modules SET state = 'active' WHERE id = 'm1'")
            conn.commit()
        finally:
            conn.close()
        assert late.acquire_hosting()
        assert _row(data, "m1")[1] == "verified"


# remove: refused offline while another process hosts ----------------------------------------------------


def test_h4_r1_f9_offline_remove_is_refused_while_another_process_hosts(
    data: Path, host: Core, capsys: pytest.CaptureFixture[str]
) -> None:
    host.run("module", "activate", {"id": "m1"}, actor="cli")
    assert _cli(data, "module", "remove", "m1") == 1
    err = capsys.readouterr().err
    assert "hosts this data directory" in err and "/switchyard module remove m1" in err
    assert "m1" in host.manager.ids() and host.manager.info("m1").status.value == "active"
    assert _row(data, "m1") == ("manual", "active")


def test_h4_r1_f9_remove_still_works_in_the_hosting_process(data: Path, host: Core) -> None:
    host.run("module", "activate", {"id": "m1"}, actor="cli")
    host.run("module", "remove", {"id": "m1"}, actor="hermes-user")
    assert "m1" not in host.manager.ids()


def test_h4_r1_f9_offline_remove_works_when_nobody_hosts(data: Path) -> None:
    assert _cli(data, "module", "remove", "m1") == 0
