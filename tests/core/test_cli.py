"""``switchyard`` command line (spec section 3, CLI)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sy_testing import write_module

from switchyard import __version__
from switchyard.api import ControlServer
from switchyard.cli import main
from switchyard.core import Core


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def data(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    write_module(d / "modules", "ext", isolation="subprocess", request=("schedule",))
    return d


def _run(data: Path, *args: str) -> list[str]:
    return ["--data-dir", str(data), *args]


def test_list_offline_json(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_run(data, "--json", "module", "list")) == 0
    [row] = json.loads(capsys.readouterr().out)
    assert row["id"] == "ext"


def test_human_output(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_run(data, "module", "list")) == 0
    out = capsys.readouterr().out
    assert "id=ext" in out and "status=verified" in out
    assert main(_run(data, "host", "profile")) == 0
    assert "profile_name:" in capsys.readouterr().out


def test_grant_offline_and_capability_denied_exit_code(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_run(data, "module", "grant", "ext", "--capability", "schedule")) == 0
    assert main(_run(data, "module", "grant", "ext", "--capability", "net.outbound")) == 3
    assert "not requested" in capsys.readouterr().err


def test_usage_error_exit_code(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_run(data, "audit", "tail", "--n", "0")) == 2
    assert "between" in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        main(_run(data, "module", "activate"))  # argparse: missing positional
    assert info.value.code == 2


def test_live_operation_needs_the_daemon(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_run(data, "module", "activate", "ext")) == 1
    assert "switchyard api serve" in capsys.readouterr().err


def test_operation_error_exit_code(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_run(data, "module", "mode", "ext", "--mode", "sometimes")) == 1
    assert "invalid mode" in capsys.readouterr().err


def test_remove_flag(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_run(data, "--json", "module", "remove", "ext", "--keep-data")) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": "ext"}


@pytest.fixture
def daemon(data: Path) -> Iterator[ControlServer]:
    core = Core(data_dir=data)
    server = ControlServer(core)
    server.start()
    yield server
    server.shutdown()
    core.close()


def test_routes_through_running_daemon(
    data: Path, daemon: ControlServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_run(data, "--json", "module", "activate", "ext")) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "active"
    assert main(_run(data, "--json", "module", "health", "ext")) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert main(_run(data, "module", "deactivate", "ext")) == 0


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_serve_runs_until_interrupted(data: Path, monkeypatch: pytest.MonkeyPatch,
                                      capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    import switchyard.cli as cli

    ticks: list[int] = []

    def fake_sleep(_s: float) -> None:
        ticks.append(1)
        if len(ticks) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", fake_sleep)
    assert main(_run(data, "api", "serve", "--port", "0")) == 0
    assert "listening on 127.0.0.1:" in capsys.readouterr().out
    assert not (data / "api.token").exists() and len(ticks) == 2


def test_default_data_dir_comes_from_the_environment(data: Path, monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    monkeypatch.setenv("SWITCHYARD_DATA_DIR", str(data))
    assert main(["--json", "module", "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "ext"


# H1 WP2: truthful exit codes and messages, daemon files, help text ---------------------------------------

PANEL_MOD = """
class Mod:
    def activate(self, ctx):
        ctx.register_panel("pan.status", lambda: {"ok": True})
    def deactivate(self):
        pass
    def health(self):
        return (True, "ok")
"""


@pytest.fixture
def pan(data: Path) -> Path:
    write_module(data / "modules", "pan", PANEL_MOD, request=("ui.panel",), isolation="subprocess")
    return data


def test_h1_d8_failed_results_exit_1_and_name_what_is_missing(
    pan: Path, daemon: ControlServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_run(pan, "module", "panel", "pan", "--panel", "pan.status")) == 1
    assert "not active" in capsys.readouterr().err
    assert main(_run(pan, "module", "activate", "pan")) == 1
    captured = capsys.readouterr()
    assert "status: failed" in captured.out and "missing_grants: ['ui.panel']" in captured.out
    assert "ui.panel" in captured.err
    assert main(_run(pan, "module", "health", "pan")) == 1
    assert main(_run(pan, "module", "grant", "pan", "--capability", "ui.panel")) == 0
    assert main(_run(pan, "module", "activate", "pan")) == 0
    assert main(_run(pan, "--json", "module", "panel", "pan", "--panel", "pan.status")) == 0


def test_h1_d26_unknown_capability_is_a_usage_error(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_run(data, "module", "grant", "ext", "--capability", "net.bogus")) == 2
    assert "unknown capability" in capsys.readouterr().err
    assert main(_run(data, "module", "revoke", "ext", "--capability", "net.bogus")) == 2


def test_h1_d10_config_show_names_the_data_directory_and_why(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_run(data, "config", "show")) == 0
    out = capsys.readouterr().out
    assert f"data_dir: {data}" in out and "data_dir_source: --data-dir" in out
    assert "api.enabled: False" in out and "{" not in out  # nested settings as key: value lines
    monkeypatch.setenv("SWITCHYARD_DATA_DIR", str(data))
    assert main(["config", "show"]) == 0
    assert "data_dir_source: SWITCHYARD_DATA_DIR" in capsys.readouterr().out


def test_h1_d9_stale_daemon_files_cost_nothing_and_are_removed(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import socket
    import time

    with socket.socket() as sock:  # a port nobody listens on
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    data.mkdir(parents=True, exist_ok=True)
    (data / "api.port").write_text(str(port), encoding="utf-8")
    (data / "api.token").write_text("stale", encoding="utf-8")
    started = time.monotonic()
    assert main(_run(data, "module", "list")) == 0
    assert time.monotonic() - started < 1.5
    assert not (data / "api.port").exists() and not (data / "api.token").exists()


def test_h1_d7_help_marks_daemon_only_operations(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["module", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "Start a module" in out and "[daemon]" in out
    assert "List every discovered module with status, mode and capabilities. [daemon]" not in out


def test_h1_d9_serve_removes_its_files_on_termination(data: Path) -> None:
    """Started and stopped the way an operator does it (Ctrl+Break on Windows, SIGTERM elsewhere); the
    readiness line must arrive through a pipe while the daemon runs (flushed)."""
    import importlib.util
    import os

    tool_path = Path(__file__).resolve().parents[2] / "tools" / "guide_walkthrough.py"
    spec = importlib.util.spec_from_file_location("guide_walkthrough_d9", tool_path)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    env = {**os.environ, "SWITCHYARD_DATA_DIR": str(data)}
    proc = tool._start_daemon(["api", "serve", "--port", "0"], env)
    try:
        assert (data / "api.port").exists() and (data / "api.token").exists()
    finally:
        tool._stop_daemon(proc)
    assert not (data / "api.port").exists() and not (data / "api.token").exists()


def test_h1_d2_config_show_names_the_git_in_use(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_run(data, "--json", "config", "show")) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["tools"]["git_configured"] is None
    assert shown["tools"]["git"] is None or Path(shown["tools"]["git"]).is_absolute()
