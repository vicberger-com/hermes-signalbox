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
