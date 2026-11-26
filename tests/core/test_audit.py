"""Hash-chained audit log (spec section 3, Audit log)."""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
from pathlib import Path

import pytest
from sy_testing import ManifestFactory

from hermes_signalbox.audit import GENESIS, AuditLog
from hermes_signalbox.capabilities import MemoryGrantStore, PolicyEngine
from hermes_signalbox.errors import AuditError, CapabilityDenied


def _clock() -> str:
    return "2026-11-19T00:00:00Z"


def _log(tmp_path: Path, **kw: object) -> AuditLog:
    return AuditLog(tmp_path / "audit", clock=_clock, **kw)  # type: ignore[arg-type]


def _lines(log_dir: Path) -> list[tuple[Path, list[str]]]:
    return [(p, p.read_text(encoding="utf-8").splitlines()) for p in sorted(log_dir.glob("audit-*.jsonl"))]


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _fill(log: AuditLog, n: int) -> None:
    for i in range(n):
        log.append(actor="user", action="test.event", module="demo", detail={"i": str(i)})


def test_chain_is_built_and_verifies(tmp_path: Path) -> None:
    log = _log(tmp_path)
    r1 = log.append(actor="user", action="a", module="demo", detail={"k": "v"})
    r2 = log.append(actor="core", action="b", module="", detail={})
    assert (r1.seq, r1.prev) == (1, GENESIS)
    assert (r2.seq, r2.prev) == (2, r1.hash)
    assert log.head == (2, r2.hash)
    result = log.verify()
    assert result.ok and result.records == 2 and result.first_bad_seq is None


def test_record_shape_on_disk(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(actor="user", action="a", module="demo", detail={"k": "v"})
    [(_, [line])] = _lines(tmp_path / "audit")
    rec = json.loads(line)
    assert set(rec) == {"seq", "ts", "actor", "action", "module", "detail", "prev", "hash"}
    assert rec["ts"] == "2026-11-19T00:00:00Z"


def test_edit_is_detected(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 5)
    [(path, lines)] = _lines(tmp_path / "audit")
    lines[2] = lines[2].replace('"i":"2"', '"i":"X"')
    _write(path, lines)
    result = _log(tmp_path).verify()
    assert not result.ok and result.first_bad_seq == 3


def test_deletion_is_detected(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 5)
    [(path, lines)] = _lines(tmp_path / "audit")
    del lines[1]
    _write(path, lines)
    assert _log(tmp_path).verify().first_bad_seq == 3


def test_reorder_is_detected(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 5)
    [(path, lines)] = _lines(tmp_path / "audit")
    lines[1], lines[2] = lines[2], lines[1]
    _write(path, lines)
    assert not _log(tmp_path).verify().ok


def test_tail_truncation_needs_the_anchor(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 5)
    head = log.head
    [(path, lines)] = _lines(tmp_path / "audit")
    _write(path, lines[:3])
    reopened = _log(tmp_path)
    assert reopened.verify().ok  # a chain cut at the end is still a valid chain ...
    result = reopened.verify(expected_head=head)  # ... which the stored head anchor exposes
    assert not result.ok and "head" in result.reason


def test_reopen_continues_the_chain(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 3)
    head = log.head
    again = _log(tmp_path)
    assert again.head == head
    rec = again.append(actor="user", action="later", module="demo", detail={})
    assert rec.seq == 4 and rec.prev == head[1]
    assert again.verify().ok


def test_torn_last_line_is_quarantined(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 2)
    [(path, _)] = _lines(tmp_path / "audit")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 3, "ts"')
    assert AuditLog.verify_directory(tmp_path / "audit").ok is False  # on disk it does not verify ...
    log = _log(tmp_path)  # ... opening repairs it (H1 A-9; before, the first append did)
    log.append(actor="user", action="after", module="demo", detail={})
    result = AuditLog.verify_directory(tmp_path / "audit")
    assert result.ok and result.records == 4
    assert [r["action"] for r in log.tail(2)] == ["audit.torn_tail_repaired", "after"]
    assert list((tmp_path / "audit").glob("*.torn-*"))  # the cut bytes are kept


def test_detail_values_are_redacted(tmp_path: Path) -> None:
    canary = "sk-CANARY-0123456789"
    log = _log(tmp_path, redact=lambda s: s.replace(canary, "[REDACTED]"))
    log.append(actor="user", action="a", module="demo", detail={"note": f"value={canary}"})
    text = (tmp_path / "audit" / "audit-000001.jsonl").read_text(encoding="utf-8")
    assert canary not in text and "[REDACTED]" in text
    assert log.verify().ok


@pytest.mark.parametrize(
    "detail", [{"n": 1}, {1: "x"}, {"long": "x" * 5000}], ids=["int-value", "int-key", "too-long"]
)
def test_bad_detail_is_refused(tmp_path: Path, detail: dict[object, object]) -> None:
    with pytest.raises(AuditError):
        _log(tmp_path).append(actor="user", action="a", module="demo", detail=detail)  # type: ignore[arg-type]


def test_rotation_keeps_one_chain(tmp_path: Path) -> None:
    log = _log(tmp_path, max_bytes=600)
    _fill(log, 12)
    files = _lines(tmp_path / "audit")
    assert len(files) > 2
    assert _log(tmp_path, max_bytes=600).verify().ok
    files[1][0].unlink()  # removing a whole file breaks the chain
    assert not _log(tmp_path, max_bytes=600).verify().ok


def test_unknown_files_are_ignored_but_bad_names_are_not_read(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 2)
    (tmp_path / "audit" / "notes.txt").write_text("hello", encoding="utf-8")
    assert _log(tmp_path).verify().ok


def test_concurrent_appends(tmp_path: Path) -> None:
    log = _log(tmp_path)
    threads = [threading.Thread(target=_fill, args=(log, 25)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    result = log.verify()
    assert result.ok and result.records == 100


def test_tail(tmp_path: Path) -> None:
    log = _log(tmp_path, max_bytes=600)
    _fill(log, 8)
    tail = log.tail(3)
    assert [r["seq"] for r in tail] == [6, 7, 8]
    assert log.tail(0) == []


def test_verify_reports_unparseable_line(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 3)
    [(path, lines)] = _lines(tmp_path / "audit")
    lines[1] = "not json"
    _write(path, [*lines, lines[2]])  # keep a valid last line so opening succeeds
    result = AuditLog.verify_directory(tmp_path / "audit")
    assert not result.ok and result.first_bad_seq == 2


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_files_are_user_only(tmp_path: Path) -> None:
    _fill(_log(tmp_path), 1)
    path = tmp_path / "audit" / "audit-000001.jsonl"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_policy_engine_writes_to_the_audit_log(tmp_path: Path, make_manifest: ManifestFactory) -> None:
    log = _log(tmp_path)
    engine = PolicyEngine(MemoryGrantStore(), log)
    engine.register(make_manifest())
    with pytest.raises(CapabilityDenied):
        engine.require("demo", "ui.panel")
    engine.grant("demo", "ui.panel", actor="user")
    assert [r["action"] for r in log.tail(10)] == ["policy.denied", "policy.granted"]
    assert log.verify().ok


def test_default_clock_and_to_dict(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit")
    rec = log.append(actor="user", action="a", module="demo", detail={})
    assert rec.ts.endswith("Z") and rec.to_dict()["hash"] == rec.hash
    assert AuditLog.verify_directory(tmp_path / "missing").ok


def test_empty_trailing_file_is_tolerated(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 2)
    head = log.head
    (tmp_path / "audit" / "audit-000002.jsonl").write_bytes(b"")
    assert _log(tmp_path).head == head
    only_empty = tmp_path / "solo"
    only_empty.mkdir()
    (only_empty / "audit-000001.jsonl").write_bytes(b"")
    assert AuditLog(only_empty).head == (0, GENESIS)


def test_unreadable_last_record_fails_closed(tmp_path: Path) -> None:
    d = tmp_path / "audit"
    d.mkdir()
    (d / "audit-000001.jsonl").write_text('{"no": "seq"}\n', encoding="utf-8")
    with pytest.raises(AuditError, match="unreadable"):
        AuditLog(d)


def test_overlong_names_are_refused(tmp_path: Path) -> None:
    with pytest.raises(AuditError, match="actor"):
        _log(tmp_path).append(actor="x" * 200, action="a", module="demo", detail={})


def test_write_failure_raises_audit_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = _log(tmp_path)

    def boom(*_a: object, **_k: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(os, "open", boom)
    with pytest.raises(AuditError, match="disk full"):
        log.append(actor="user", action="a", module="demo", detail={})
    monkeypatch.undo()
    assert log.head == (0, GENESIS)  # a failed write does not advance the chain


def _tamper(tmp_path: Path, index: int, edit: object) -> None:
    [(path, lines)] = _lines(tmp_path / "audit")
    rec = json.loads(lines[index])
    edit(rec)  # type: ignore[operator]
    lines[index] = json.dumps(rec)
    _write(path, lines)


def test_wrong_fields_detected(tmp_path: Path) -> None:
    _fill(_log(tmp_path), 3)
    _tamper(tmp_path, 1, lambda r: r.update(extra="x"))
    assert AuditLog.verify_directory(tmp_path / "audit").reason == "record has the wrong fields"


def test_prev_rewrite_detected(tmp_path: Path) -> None:
    # Recomputing the hash of an edited record is not enough: its successor's prev no longer matches.
    from hermes_signalbox.audit import record_hash

    _fill(_log(tmp_path), 3)

    def forge(r: dict[str, object]) -> None:
        r["detail"] = {"i": "forged"}
        r["hash"] = record_hash(r)

    _tamper(tmp_path, 1, forge)
    result = AuditLog.verify_directory(tmp_path / "audit")
    assert not result.ok and result.first_bad_seq == 3 and "prev" in result.reason


def test_anchor_hash_mismatch_detected(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 3)
    seq, _ = log.head
    result = log.verify(expected_head=(seq, "f" * 64))
    assert not result.ok and "anchor" in result.reason
    assert log.verify(expected_head=(2, log.tail(2)[0]["hash"])).ok  # an older anchor is fine


# H1 WP9: audit log and startup ------------------------------------------------------------------------------


def test_h1_a8_tail_survives_unicode_line_separators(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(actor="user", action="a", module="demo", detail={"note": "one\u2028two\u2029three\x85"})
    log.append(actor="user", action="b", module="demo", detail={})
    assert [r["action"] for r in log.tail(5)] == ["a", "b"]
    assert log.tail(1)[0]["action"] == "b"


def test_h1_a9_torn_tail_is_repaired_on_open_and_not_tampering(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 2)
    [(path, _)] = _lines(tmp_path / "audit")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 3, "ts"')
    log = _log(tmp_path)  # opening repairs the never-anchored torn record
    result = AuditLog.verify_directory(tmp_path / "audit", (2, log.tail(3)[1]["hash"]))
    assert result.ok and result.records == 3
    assert log.tail(1)[0]["action"] == "audit.torn_tail_repaired"
    assert list((tmp_path / "audit").glob("*.torn-*"))


def test_h1_a9_stripped_final_newline_fails_verify(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 3)
    [(path, _)] = _lines(tmp_path / "audit")
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    result = AuditLog.verify_directory(tmp_path / "audit")
    assert not result.ok and "not terminated" in result.reason


def test_h1_a12_bad_bytes_and_deep_json_are_reported_not_raised(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _fill(log, 3)
    [(path, _)] = _lines(tmp_path / "audit")
    data = path.read_bytes().split(b"\n")
    # not utf-8, or nesting that exhausts older parsers (3.14 parses it; it then has the wrong fields)
    for bad, reason in (
        (b"\xff\xfe not utf-8", "unparseable"),
        (b"[" * 100_000 + b"]" * 100_000, "unparseable"),
    ):
        lines = list(data)
        lines[1] = bad
        path.write_bytes(b"\n".join(lines))
        result = AuditLog.verify_directory(tmp_path / "audit")
        assert not result.ok and result.first_bad_seq == 2, (reason, result)


def test_h1_a13_large_last_record_does_not_stop_appends(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(actor="user", action="big", module="demo", detail={f"k{i}": "v" * 1000 for i in range(70)})
    log = _log(tmp_path)  # the last record is larger than one tail probe ... reopening still finds it
    log.append(actor="user", action="after", module="demo", detail={})
    assert AuditLog.verify_directory(tmp_path / "audit").ok
    with pytest.raises(AuditError, match="too large"):
        log.append(
            actor="user", action="huge", module="demo", detail={f"k{i}": "v" * 1000 for i in range(140)}
        )


def test_h1_a14_short_write_is_completed_or_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = _log(tmp_path)
    real = os.write
    calls = {"n": 0}

    def half(fd: int, data: bytes) -> int:
        calls["n"] += 1
        return real(fd, bytes(data[: max(1, len(data) // 2)]))

    monkeypatch.setattr(os, "write", half)
    log.append(actor="user", action="a", module="demo", detail={"x": "y" * 50})
    monkeypatch.setattr(os, "write", real)
    assert calls["n"] > 1 and AuditLog.verify_directory(tmp_path / "audit").ok

    monkeypatch.setattr(os, "write", lambda fd, data: 0)
    with pytest.raises(AuditError, match="no progress"):
        log.append(actor="user", action="b", module="demo", detail={})
    monkeypatch.setattr(os, "write", real)
    assert log.head[0] == 1


def test_h1_a2_long_denial_detail_is_truncated_and_recorded(
    tmp_path: Path, make_manifest: ManifestFactory
) -> None:
    log = _log(tmp_path)
    policy = PolicyEngine(MemoryGrantStore(), log)
    policy.register(make_manifest("demo", request=["net.outbound"], net_hosts=["ok.example"]))
    policy.grant("demo", "net.outbound", actor="user")
    with pytest.raises(CapabilityDenied):
        policy.require_host("demo", "h" * 5000)
    with pytest.raises(CapabilityDenied):
        policy.require("demo", "ui.panel", panel="p" * 5000)
    denied = [r for r in log.tail(10) if r["action"] == "policy.denied"]
    assert len(denied) == 2 and all(len(v) <= 1024 for r in denied for v in r["detail"].values())
    assert denied[0]["detail"]["host"].endswith("[+4020 chars]")
