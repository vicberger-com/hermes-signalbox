"""1.1 backlog batch 8: log redaction covers keys (H1 B-23 #112)."""

from __future__ import annotations

import json
from pathlib import Path

from switchyard.logs import JsonlLogSink

SECRET = "sekret-" + "5e1f9a0c7b"


def _sink(tmp_path: Path) -> JsonlLogSink:
    return JsonlLogSink(tmp_path, redact=lambda s: s.replace(SECRET, "[R]"), clock=lambda: "T")


def _line(tmp_path: Path) -> str:
    return (tmp_path / "events.jsonl").read_text(encoding="utf-8")


def test_h1_b23_a_secret_used_as_a_field_name_is_redacted(tmp_path: Path) -> None:
    _sink(tmp_path).write("demo", "events", "e", {SECRET: 1, "nested": {f"k-{SECRET}": "v"}})
    text = _line(tmp_path)
    assert SECRET not in text
    record = json.loads(text)
    assert record["fields"] == {"[R]": 1, "nested": {"k-[R]": "v"}}


def test_h1_b23_keys_that_redact_alike_are_all_kept(tmp_path: Path) -> None:
    _sink(tmp_path).write("demo", "events", "e", {SECRET: 1, "[R]": 2})  # both become "[R]"
    fields = json.loads(_line(tmp_path))["fields"]
    assert sorted(fields.values()) == [1, 2] and SECRET not in json.dumps(fields)
