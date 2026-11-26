"""M11 offload: proprietary connectors off until allowed by name; data-sent declaration enforced."""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from hermes_signalbox.contract import run_contract
from hermes_signalbox.core import BUILTIN_MODULES, Core
from hermes_signalbox.errors import CapabilityDenied, SignalboxError

pytestmark = pytest.mark.bundled_modules
MODULE_DIR = Path(BUILTIN_MODULES) / "offload"
RECEIVED: list[dict[str, Any]] = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RECEIVED.append({"path": self.path, "body": body})
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.com/x")
            self.end_headers()
            return
        if self.path == "/trickle":
            import time as _t

            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            for _ in range(100):
                self.wfile.write(b"x")
                self.wfile.flush()
                _t.sleep(0.1)
            return
        if self.path == "/short":
            self.send_response(200)
            self.send_header("Content-Length", "10000")
            self.end_headers()
            self.wfile.write(b"x" * 100)
            return
        if self.path == "/big":
            payload = b"x" * 4_100_000
        elif self.path == "/fail":
            self.send_response(500)
            self.end_headers()
            return
        else:
            payload = json.dumps({"answer": "yes", "echo": sorted(body)}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture(scope="module")
def server() -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes"))


def start(data: Path, config: str, spawn: bool = True) -> Core:
    data.mkdir(parents=True, exist_ok=True)
    (data / "config.toml").write_text(f"[modules.offload]\n{config}\n", encoding="utf-8")
    c = Core(data_dir=data, hosting=True)
    for cap in ("net.outbound", "ui.panel") + (("process.spawn",) if spawn else ()):
        c.run("module", "grant", {"id": "offload", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "offload"}, actor="t")
    return c


def off(core: Core, action: str, actor: str = "t", **args: Any) -> Any:
    return core.run("module", "action", {"id": "offload", "action": action, "args": args}, actor=actor)


@pytest.fixture
def core(tmp_path: Path, server: int) -> Iterator[Core]:
    c = start(
        tmp_path / "d",
        f'jevk5_url = "http://127.0.0.1:{server}/v1/systemone"\n'
        f'n8n_webhook = "http://localhost:{server}/webhook/secret-id"',
    )
    yield c
    c.close()


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_open_connector_and_data_sent_enforced(core: Core) -> None:
    RECEIVED.clear()
    out = off(core, "run", connector="jevk5", payload=json.dumps({"state": "doc", "questions": {"q": {}}}))
    assert out["result"] == {"answer": "yes", "echo": ["questions", "state"]}
    with pytest.raises(SignalboxError, match="refused \\['api_key'\\]"):
        off(core, "run", connector="jevk5", payload=json.dumps({"state": "doc", "api_key": "sk-x"}))
    assert len(RECEIVED) == 1  # nothing sent for the refused payload
    tail = [
        r for r in core.run("audit", "tail", {"n": 30}, actor="t") if r["action"] == "module.offload.offload"
    ]
    assert tail and "doc" not in json.dumps(tail)  # field names only
    for bad in ("not json", "[]", "{}"):
        with pytest.raises(SignalboxError):
            off(core, "run", connector="jevk5", payload=bad)


def test_proprietary_connectors_off_until_allowed(
    core: Core, tmp_path: Path, server: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = {c["name"]: c for c in off(core, "connectors", actor="hermes")["connectors"]}
    assert (
        listing["jevk5"]["enabled"]
        and not listing["n8n"]["enabled"]
        and not listing["claude-code"]["enabled"]
    )
    assert "secret-id" not in json.dumps(listing)  # webhook paths are credentials
    for name, payload in (
        ("n8n", {"task": "x"}),
        ("claude-code", {"prompt": "hi"}),
        ("codex", {"prompt": "hi"}),
    ):
        with pytest.raises(SignalboxError, match="allow it by name"):
            off(core, "run", connector=name, payload=json.dumps(payload))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude_fake.py"
    script.write_text(
        "import os, sys\nprint('echo:' + sys.stdin.read().strip() + ' ' + str(os.listdir('.')))\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        (bin_dir / "claude.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        (bin_dir / "claude").write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
        )
        (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    c = start(
        tmp_path / "d2",
        f'allow = ["n8n", "claude-code"]\nn8n_webhook = "http://localhost:{server}/webhook/w"',
    )
    try:
        assert off(c, "run", connector="n8n", payload=json.dumps({"task": "t"}))["result"]["answer"] == "yes"
        out = off(c, "run", connector="claude-code", payload=json.dumps({"prompt": "hello"}))["result"]
        assert out.strip() == "echo:hello []"  # ran in an empty working directory
        from hermes_signalbox.modules.offload.offload_module import ARGV  # type: ignore[import-not-found,unused-ignore]

        assert ARGV["claude"][-2:] == ["--tools", ""]  # no tools: the agent cannot read local files
        with pytest.raises(SignalboxError, match="allow it by name"):
            off(c, "run", connector="codex", payload=json.dumps({"prompt": "x"}))
        assert off(c, "report")["runs"]["n8n"] == {"runs": 1, "failures": 0}
    finally:
        c.close()


def test_net_broker_rules(core: Core, server: int) -> None:
    net = core.manager._entry("offload").instance.ctx.net
    base = f"http://127.0.0.1:{server}"
    with pytest.raises(CapabilityDenied):
        net.request("POST", "http://example.com/x", json={})
    for bad in ("ftp://127.0.0.1/x", f"http://user:pw@127.0.0.1:{server}/x", "http:///x"):
        with pytest.raises(SignalboxError):
            net.request("POST", bad, json={})
    with pytest.raises(SignalboxError):
        net.request("TRACE", base + "/x")
    resp = net.request("POST", base + "/redirect", json={})
    assert resp.status == 302  # not followed
    big = net.request("POST", base + "/big", json={})
    assert big.truncated
    assert net.request("POST", base + "/fail", json={}).status == 500
    with pytest.raises(SignalboxError, match="failed"):
        net.request("POST", "http://127.0.0.1:1/x", json={}, timeout=1)
    import time

    started = time.monotonic()
    with pytest.raises(SignalboxError, match="failed"):  # total deadline, not per read
        net.request("POST", base + "/trickle", json={}, timeout=1)
    assert time.monotonic() - started < 5
    with pytest.raises(SignalboxError, match="failed"):  # closed before Content-Length: not a success
        net.request("POST", base + "/short", json={})
    for bad in ("http://127.0.0.1:99999/x", "http://127.0.0.1:abc/x", "http://[127.0.0.1]:8090/x"):
        with pytest.raises(SignalboxError):
            net.request("POST", bad, json={})
    actions = [r for r in core.run("audit", "tail", {"n": 50}, actor="t") if r["action"] == "net.request"]
    assert actions and all("/" not in r["detail"]["host"] for r in actions)


def test_failures_settings_and_rights(core: Core, tmp_path: Path, server: int) -> None:
    c = start(tmp_path / "d3", f'jevk5_url = "http://127.0.0.1:{server}/fail"')
    try:
        with pytest.raises(SignalboxError, match="HTTP 500"):
            off(c, "run", connector="jevk5", payload=json.dumps({"state": "x"}))
        assert off(c, "report")["runs"]["jevk5"] == {"runs": 1, "failures": 1}
    finally:
        c.close()
    with pytest.raises(SignalboxError, match="read-only"):
        off(core, "run", actor="hermes", connector="jevk5", payload="{}")
    with pytest.raises(SignalboxError, match="unknown connector"):
        off(core, "run", connector="nope", payload="{}")
    for i, bad in enumerate(
        (
            'jevk5_url = "http://10.0.0.5:8090/x"',
            'n8n_webhook = "https://example.com/w"',
            'allow = ["skynet"]',
            "timeout_seconds = 1",
            "nonsense = 1",
        )
    ):
        c = start(tmp_path / f"b{i}", bad)
        try:
            assert c.run("module", "show", {"id": "offload"}, actor="t")["status"] == "failed"
        finally:
            c.close()
    c = start(tmp_path / "d4", "allow = ['codex', 'n8n']", spawn=False)
    try:
        with pytest.raises(SignalboxError, match=r"process\.spawn"):
            off(c, "run", connector="codex", payload=json.dumps({"prompt": "x"}))
        with pytest.raises(SignalboxError, match=r"n8n_webhook"):
            off(c, "run", connector="n8n", payload=json.dumps({"task": "x"}))
    finally:
        c.close()


def test_h1_1_cleanup_failure_after_a_successful_run_does_not_fail_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#126: on Windows a Claude Code child that outlives the CLI holds the empty working directory, so
    removing it raised PermissionError and failed a run whose program had exited 0."""
    import shutil

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude_fake.py"
    script.write_text("import sys\nprint('ok:' + sys.stdin.read().strip())\n", encoding="utf-8")
    if os.name == "nt":
        (bin_dir / "claude.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        shim = f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n'
        (bin_dir / "claude").write_text(shim, encoding="utf-8")
        (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    real_rmtree = shutil.rmtree
    held: list[str] = []

    def held_open(path: Any, *args: Any, **kwargs: Any) -> None:
        if "signalbox-offload-" in str(path):
            held.append(str(path))
            raise PermissionError(13, "The process cannot access the file", str(path))
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", held_open)
    c = start(tmp_path / "d5", 'allow = ["claude-code"]')
    try:
        out = off(c, "run", connector="claude-code", payload=json.dumps({"prompt": "hi"}))
        assert out["result"].strip() == "ok:hi"
        assert len(held) == 1 + len(_offload_mod().CLEANUP_RETRY_DELAYS)  # tried, retried, then given up
        logs = (tmp_path / "d5" / "logs").rglob("*.jsonl")
        text = "".join(p.read_text(encoding="utf-8") for p in logs)
        assert "workdir_cleanup_failed" in text and "PermissionError" in text  # the failed step is recorded
    finally:
        c.close()
        monkeypatch.undo()
        for path in held:
            real_rmtree(path, ignore_errors=True)


def _offload_mod() -> Any:
    from hermes_signalbox.modules.offload import offload_module  # type: ignore[import-not-found,unused-ignore]

    return offload_module


@pytest.fixture(autouse=True)
def _restore_retry_delays() -> Iterator[None]:
    saved = _offload_mod().CLEANUP_RETRY_DELAYS
    yield
    _offload_mod().CLEANUP_RETRY_DELAYS = saved


def test_h1_1_a_briefly_held_workdir_is_removed_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    mod = _offload_mod()
    mod.CLEANUP_RETRY_DELAYS = (0.0, 0.0)
    real_rmtree = shutil.rmtree
    calls: list[str] = []

    def held_once(path: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(str(path))
        if len(calls) == 1:
            raise PermissionError(13, "held", str(path))
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", held_once)
    work = tmp_path / "w"
    work.mkdir()
    logged: list[str] = []
    fake = type("M", (), {"ctx": type("C", (), {"log": lambda self, *a, **k: logged.append(a[1])})()})()
    mod.OffloadModule._remove_workdir(fake, str(work), "claude-code")
    assert not work.exists() and len(calls) == 2 and logged == []


def test_h1_1_stale_empty_workdirs_are_swept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tempfile

    mod = _offload_mod()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    old_empty = tmp_path / f"{mod.WORKDIR_PREFIX}old"
    old_full = tmp_path / f"{mod.WORKDIR_PREFIX}full"
    fresh = tmp_path / f"{mod.WORKDIR_PREFIX}fresh"
    other = tmp_path / "unrelated-old"
    for d in (old_empty, old_full, fresh, other):
        d.mkdir()
    (old_full / "keep.txt").write_text("x", encoding="utf-8")
    now = 10_000_000.0
    for d in (old_empty, old_full, other):
        os.utime(d, (now - 3600, now - 3600))
    os.utime(fresh, (now - 5, now - 5))
    mod.OffloadModule._sweep_stale_workdirs(now)
    assert not old_empty.exists()
    assert old_full.exists() and fresh.exists() and other.exists()
