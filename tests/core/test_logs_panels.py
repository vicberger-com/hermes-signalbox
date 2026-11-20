"""JSON Lines log sink and in-memory panel registry."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from switchyard.context import MemoryPanelRegistry
from switchyard.errors import SwitchyardError
from switchyard.logs import MAX_LINE_BYTES, JsonlLogSink


def test_lines_are_json_per_stream(tmp_path: Path) -> None:
    sink = JsonlLogSink(tmp_path / "logs", clock=lambda: "T")
    sink.write("demo", "demo", "started", {"n": 1, "path": Path("x")})
    sink.write("demo", "demo.debug", "tick", {})
    lines = (tmp_path / "logs" / "demo.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"ts": "T", "module": "demo", "stream": "demo", "event": "started",
                                    "fields": {"n": 1, "path": "x"}}  # fmt: skip
    assert (tmp_path / "logs" / "demo.debug.jsonl").exists()


def test_redaction_applies_to_every_string(tmp_path: Path) -> None:
    canary = "sk-CANARY-42"
    sink = JsonlLogSink(tmp_path, redact=lambda s: s.replace(canary, "[R]"))
    sink.write("demo", "demo", f"event {canary}", {"k": canary, "nested": {"v": [canary]}})
    text = (tmp_path / "demo.jsonl").read_text(encoding="utf-8")
    assert canary not in text and text.count("[R]") == 3


@pytest.mark.parametrize("stream", ["../escape", "a/b", "A", "", "x" * 80])
def test_bad_stream_names_are_refused(tmp_path: Path, stream: str) -> None:
    with pytest.raises(SwitchyardError, match="stream"):
        JsonlLogSink(tmp_path).write("demo", stream, "e", {})


def test_oversize_line_is_truncated(tmp_path: Path) -> None:
    sink = JsonlLogSink(tmp_path)
    sink.write("demo", "demo", "big", {"blob": "x" * (MAX_LINE_BYTES * 2)})
    line = (tmp_path / "demo.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["fields"] == {"truncated": True} and len(line) <= MAX_LINE_BYTES


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_log_files_are_user_only(tmp_path: Path) -> None:
    JsonlLogSink(tmp_path).write("demo", "demo", "e", {})
    assert stat.S_IMODE(os.stat(tmp_path / "demo.jsonl").st_mode) == 0o600


def test_panel_registry() -> None:
    reg = MemoryPanelRegistry()
    reg.add("a", "a.status", lambda: {"x": 1})
    reg.add("b", "b.status", dict)
    assert reg.panels("a") == ["a.status"] and reg.render("a", "a.status") == {"x": 1}
    reg.remove_all("a")
    assert reg.panels("a") == [] and reg.panels("b") == ["b.status"]
    with pytest.raises(SwitchyardError, match="panel"):
        reg.render("a", "a.status")
