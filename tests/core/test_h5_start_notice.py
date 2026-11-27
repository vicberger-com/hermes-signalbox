"""H5, issue #221 item 2 (operator decision Q-SY-H5-CLOSE-1 (3)): a module set to start with Hermes that is
still missing permissions used to be skipped with only an audit record. The hosting process now says so at
start-up, once, in words, with the command that fixes it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from sy_testing import write_module

from hermes_signalbox import present
from hermes_signalbox.cli import _announce_waiting
from hermes_signalbox.core import Core
from hermes_signalbox.hermes import HermesAdapter


@pytest.fixture
def data(tmp_path: Path) -> Path:
    mods = tmp_path / "modules"
    write_module(mods, "needy", isolation="subprocess", activation="auto", request=("schedule", "ui.panel"))
    write_module(mods, "ready", isolation="subprocess", activation="auto")
    write_module(mods, "byhand", isolation="subprocess", activation="manual", request=("schedule",))
    return tmp_path


def test_h5_221_start_auto_reports_what_it_skipped_and_why(data: Path) -> None:
    with Core(data_dir=data, hosting=True) as core:
        skipped = core.manager.start_auto(actor="core")
        assert skipped == {"needy": ["schedule", "ui.panel"]}  # not the manual module, not the started one
        assert core.manager.info("ready").status.value == "active"
        actions = [r["action"] for r in core.run("audit", "tail", {"n": 20}, actor="cli")]
        assert "module.auto_skipped" in actions  # the audit record is still written
        core.run("module", "grant", {"id": "needy", "capability": "schedule"}, actor="cli")
        core.run("module", "grant", {"id": "needy", "capability": "ui.panel"}, actor="cli")
        assert core.manager.start_auto(actor="core") == {}


def test_h5_221_the_notice_names_each_module_its_permissions_and_the_command() -> None:
    lines = present.start_notice(
        {"needy": ["schedule", "ui.panel"], "meter": ["hermes.hooks"]}, "hermes signalbox"
    )
    assert lines[0] == (
        "Signalbox: 2 modules set to start with Hermes were not started because they are missing "
        "permissions. Grant them, or set a module's start mode to manual to stop this notice."
    )
    assert lines[1] == (
        "meter needs 1 permission: Watch and steer Hermes requests (hermes.hooks). "
        "Grant it with: hermes signalbox module grant meter --capability hermes.hooks"
    )
    assert lines[2] == (
        "needy needs 2 permissions: Run on a timer (schedule), Show a dashboard panel (ui.panel). "
        "Grant each with: hermes signalbox module grant needy --capability schedule"
    )
    assert present.start_notice({}, "hermes signalbox") == []
    one = present.start_notice({"meter": ["hermes.hooks"]}, "hermes-signalbox")
    assert one[0].startswith(
        "Signalbox: 1 module set to start with Hermes was not started because it is missing"
    )
    assert one[1].endswith("hermes-signalbox module grant meter --capability hermes.hooks")


def test_h5_221_hermes_logs_the_notice_when_it_starts_hosting(
    data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with Core(data_dir=data, hosting=True) as core:
        adapter = HermesAdapter.__new__(HermesAdapter)
        adapter.core = core
        adapter._server = None
        with caplog.at_level(logging.WARNING, logger="signalbox"):
            adapter._start_hosting()
        messages = [r.getMessage() for r in caplog.records if r.name == "signalbox"]
        assert len(messages) == 2 and all(r.levelno == logging.WARNING for r in caplog.records)
        assert messages[0].startswith("Signalbox: 1 module set to start with Hermes was not started")
        assert "hermes signalbox module grant needy --capability schedule" in messages[1]
        assert core.manager.info("ready").status.value == "active"


def test_h5_221_nothing_is_logged_when_every_auto_module_started(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_module(tmp_path / "modules", "ready", isolation="subprocess", activation="auto")
    with Core(data_dir=tmp_path, hosting=True) as core:
        adapter = HermesAdapter.__new__(HermesAdapter)
        adapter.core = core
        adapter._server = None
        with caplog.at_level(logging.WARNING, logger="signalbox"):
            adapter._start_hosting()
        assert [r for r in caplog.records if r.name == "signalbox"] == []


def test_h5_221_the_daemon_prints_the_notice_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    _announce_waiting({"needy": ["schedule"]}, "hermes-signalbox")
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout carries the readiness line service managers parse
    assert "needy needs 1 permission: Run on a timer (schedule)." in captured.err
    assert "hermes-signalbox module grant needy --capability schedule" in captured.err
    _announce_waiting({}, "hermes-signalbox")
    assert capsys.readouterr().err == ""
