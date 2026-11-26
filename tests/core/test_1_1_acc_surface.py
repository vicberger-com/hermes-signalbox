"""1.1 acceptance security review, surfaces: audit before argument binding, the redactor's memory, config
rollback when the key cannot be read, dashboard URLs (S3-5, S2-5, S2-6, S3-7)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hermes_signalbox import ops, secrets
from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.hermesconfig import ConfigWriter
from hermes_signalbox.ops import UsageError

ROOT = Path(__file__).resolve().parents[2]


class _Action:
    def __init__(self, handler: Any, params: dict[str, Any]) -> None:
        self.name = "act"
        self.handler = handler
        self.params = params
        self.read_only = False


class _Sink:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(self, *, actor: str, action: str, module: str, detail: dict[str, str]) -> None:
        self.records.append({"action": action, "module": module, "detail": dict(detail)})


def test_s3_5_a_call_refused_at_argument_binding_is_still_audited() -> None:
    def handler(text: str, count: int) -> Any:
        return text * count

    sink = _Sink()
    core = SimpleNamespace(
        actions=SimpleNamespace(get=lambda m, n: _Action(handler, {"text": str})), audit=sink
    )
    with pytest.raises(UsageError, match="missing argument"):
        ops.run_action(core, "demo", "act", {"text": "hi"}, actor="cli", read_only_only=False)  # type: ignore[arg-type]
    assert [r["action"] for r in sink.records] == ["module.action"]


def test_s2_5_a_secret_stays_redacted_after_many_newer_values() -> None:
    rd = secrets.Redactor()
    rd.add("leakme-0000-value", "bw")
    for i in range(1000):
        rd.add(f"other-secret-{i:05d}", "bw")
    assert "leakme-0000-value" not in rd.redact("token=leakme-0000-value")


class _Port:
    def __init__(self) -> None:
        self.value = ["a"]
        self.writes: list[list[str]] = []
        self.reads = 0

    def get(self, key: str) -> Any:
        self.reads += 1
        if self.reads == 1:
            return list(self.value)
        if self.reads == 2:
            return ["a", "b", "intruder"]  # read-back after our write: a name we did not write
        raise OSError("config unreadable")  # the rollback's own read fails

    def set(self, key: str, value: Any) -> None:
        self.writes.append(list(value))
        self.value = list(value)

    def skills(self) -> list[dict[str, str]]:
        return [{"name": n} for n in ("a", "b", "intruder")]

    def essential(self) -> frozenset[str]:
        return frozenset()


def test_s2_6_a_rollback_that_cannot_read_the_key_does_not_write_blind(tmp_path: Path) -> None:
    port, sink = _Port(), _Sink()
    with pytest.raises(SignalboxError, match="NOT restored"):
        ConfigWriter(port, sink, tmp_path / "b").set("activation", "skills.disabled", ["a", "b"], actor="t")  # type: ignore[arg-type]
    assert port.writes == [["a", "b"]]  # no restore written over a value nobody could read
    rollback = [r for r in sink.records if r["action"] == "hermes.config.rollback"]
    assert rollback and rollback[-1]["detail"]["restored"] == "unknown"


def test_s3_7_dashboard_module_urls_encode_the_id() -> None:
    js = (ROOT / "dashboard" / "dist" / "index.js").read_text(encoding="utf-8")
    assert '"/modules/" + m.id' not in js
    assert "encodeURIComponent(m.id)" in js
