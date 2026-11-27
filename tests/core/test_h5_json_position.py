"""Usability review of the 1.1.0 release candidate: the text output ends with "Raw data: add --json.", and
adding it at the end of the same command was refused. The flag is accepted in both places, and usage and
error text name the command the person typed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_signalbox import cli


def _run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *argv: str, prog: str = "hermes-signalbox"
) -> str:
    assert cli.main(["--data-dir", str(tmp_path / "data"), *argv], prog=prog) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [("module", "list", "--json"), ("--json", "module", "list"), ("config", "show", "--json")],
)
def test_h5_json_is_accepted_before_and_after_the_operation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    json.loads(_run(tmp_path, capsys, *argv))


def test_h5_the_hint_in_the_text_output_works_as_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _run(tmp_path, capsys, "module", "list")
    assert "add --json" in text
    json.loads(_run(tmp_path, capsys, "module", "list", "--json"))


def test_h5_without_the_flag_the_output_stays_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(json.JSONDecodeError):
        json.loads(_run(tmp_path, capsys, "module", "list"))


def test_h5_usage_names_the_command_that_was_typed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--data-dir", str(tmp_path / "data"), "module", "list", "--nope"], prog="hermes signalbox")
    err = capsys.readouterr().err
    assert "usage: hermes signalbox" in err and "hermes-signalbox" not in err
