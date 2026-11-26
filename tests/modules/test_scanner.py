"""M10 scanner: seeded-vulnerability fixtures are detected; scanner failure is reported, never silent."""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hermes_signalbox.contract import run_contract
from hermes_signalbox.core import BUILTIN_MODULES, Core
from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.modules.scanner import parsers  # type: ignore[import-not-found,unused-ignore]

pytestmark = pytest.mark.bundled_modules
MODULE_DIR = Path(BUILTIN_MODULES) / "scanner"
FIX = Path(__file__).parent.parent / "fixtures" / "scanners"
SEEDED = FIX / "seeded"


def sc(core: Core, action: str, actor: str = "t", **args: Any) -> Any:
    return core.run("module", "action", {"id": "scanner", "action": action, "args": args}, actor=actor)


def fake_tool(bin_dir: Path, name: str, stdout_file: Path | None, code: int = 1, text: str = "") -> None:
    """A stand-in scanner on PATH that prints a recorded output and exits with ``code``."""
    script = bin_dir / f"{name}_fake.py"
    payload = (
        f"print(open({str(stdout_file)!r}, encoding='utf-8').read())" if stdout_file else f"print({text!r})"
    )
    script.write_text(f"import sys\n{payload}\nsys.exit({code})\n", encoding="utf-8")
    if os.name == "nt":
        (bin_dir / f"{name}.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = bin_dir / name
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes"))


def start(data: Path, config: str) -> Core:
    data.mkdir(parents=True, exist_ok=True)
    (data / "config.toml").write_text(f"[modules.scanner]\n{config}\n", encoding="utf-8")
    c = Core(data_dir=data, hosting=True)
    for cap in ("process.spawn", "schedule", "ui.panel", "notify"):
        c.run("module", "grant", {"id": "scanner", "capability": cap}, actor="t")
    for cap in ("core.read", "ui.panel"):
        c.run("module", "grant", {"id": "inbox", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "inbox"}, actor="t")
    c.run("module", "activate", {"id": "scanner"}, actor="t")
    return c


@pytest.fixture
def fakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("gitleaks", "pip-audit", "osv-scanner", "semgrep", "trivy"):
        fake_tool(bin_dir, name, FIX / f"{name}.json", code=0 if name == "trivy" else 1)
    monkeypatch.setenv(
        "PATH",
        str(bin_dir)
        + os.pathsep
        + str(Path(sys.executable).parent)
        + os.pathsep
        + os.environ.get("PATH", ""),
    )
    return bin_dir


@pytest.fixture
def core(tmp_path: Path, fakes: Path) -> Iterator[Core]:
    target = str(SEEDED).replace("\\", "/")
    c = start(tmp_path / "data", f'targets = ["{target}"]\ntimeout_seconds = 120')
    yield c
    c.close()


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_parsers_on_recorded_outputs() -> None:
    leaks = parsers.parse_gitleaks((FIX / "gitleaks.json").read_text("utf-8"))
    assert leaks[0]["rule"] == "aws-access-token" and "REDACTED" not in str(leaks)  # the match is never kept
    assert parsers.parse_pip_audit((FIX / "pip-audit.json").read_text("utf-8"))[0]["rule"] == "PYSEC-2018-28"
    assert (
        parsers.parse_osv((FIX / "osv-scanner.json").read_text("utf-8"))[0]["rule"] == "GHSA-x84v-xcm2-53pg"
    )
    assert parsers.parse_semgrep((FIX / "semgrep.json").read_text("utf-8"))[0]["severity"] == "high"
    trivy = parsers.parse_trivy((FIX / "trivy.json").read_text("utf-8"))
    assert {f["severity"] for f in trivy} == {"high", "critical"} and "AKIA" not in str(trivy)
    assert parsers.parse_gitleaks("[]") == [] and parsers.parse_osv('{"results": []}') == []
    for parse in (parsers.parse_gitleaks, parsers.parse_osv):  # no output is a failure, not an all-clear
        with pytest.raises(parsers.ParseError):
            parse("")
    for parse in (parsers.parse_bandit, parsers.parse_semgrep, parsers.parse_trivy, parsers.parse_pip_audit):
        with pytest.raises(parsers.ParseError):
            parse("not json")
        with pytest.raises(parsers.ParseError):
            parse("[1, 2]")


def test_seeded_vulnerabilities_are_detected(core: Core) -> None:
    out = sc(core, "run_now")
    assert out["runs"] == 6
    found = sc(core, "findings", limit=1000)["findings"]
    by_scanner = {f["scanner"] for f in found}
    expected = {"gitleaks", "pip-audit", "osv-scanner", "semgrep", "trivy"}
    if shutil.which("bandit"):  # the real bandit, run on the seeded file
        expected.add("bandit")
        rules = {f["rule"] for f in found if f["scanner"] == "bandit"}
        assert {"B602", "B301"} & rules, rules
    assert expected <= by_scanner, by_scanner
    items = core.run("module", "action", {"id": "inbox", "action": "list", "args": {}}, actor="t")["items"]
    assert any("trivy" in i["title"] for i in items)  # new high/critical findings are announced
    again = sc(core, "run_now")
    assert again["new"] == 0  # de-duplicated
    report = sc(core, "report", actor="hermes")
    assert report["open"] and report["recent_runs"]


def test_scanner_failure_is_reported_never_silent(core: Core, fakes: Path) -> None:
    fake_tool(fakes, "semgrep", None, code=2, text="fatal: rules could not be fetched")
    fake_tool(fakes, "osv-scanner", None, code=0, text="<html>not json</html>")
    for name in ("trivy",):
        for ext in (".cmd", ""):
            p = fakes / f"{name}{ext}"
            if p.exists():
                p.unlink()
    sc(core, "run_now")
    failed = {f["rule"]: f for f in sc(core, "findings", limit=1000)["findings"] if f["scanner"] == "scanner"}
    assert {"semgrep:failed", "osv-scanner:failed", "trivy:failed"} <= set(failed)
    assert (
        "exit 2" in failed["semgrep:failed"]["title"] and "not JSON" in failed["osv-scanner:failed"]["title"]
    )
    assert "not found" in failed["trivy:failed"]["title"]
    items = core.run("module", "action", {"id": "inbox", "action": "list", "args": {}}, actor="t")["items"]
    assert any("semgrep failed" in i["title"] for i in items)
    assert core.run("module", "show", {"id": "scanner"}, actor="t")  # health reports failures
    fake_tool(fakes, "semgrep", FIX / "semgrep.json", code=1)
    sc(core, "run_now")
    open_fail = [f for f in sc(core, "findings", limit=1000)["findings"] if f["rule"] == "semgrep:failed"]
    assert open_fail == []  # resolved once it runs again


def test_findings_resolve_when_fixed(core: Core, fakes: Path) -> None:
    sc(core, "run_now")
    empty = fakes / "empty.json"
    empty.write_text('{"results": [], "errors": []}', encoding="utf-8")
    fake_tool(fakes, "semgrep", empty, code=0)
    sc(core, "run_now")
    assert not [f for f in sc(core, "findings")["findings"] if f["scanner"] == "semgrep"]
    assert [
        f for f in sc(core, "findings", state="resolved", limit=1000)["findings"] if f["scanner"] == "semgrep"
    ]


def test_settings_and_permissions(tmp_path: Path, fakes: Path) -> None:
    for i, bad in enumerate(
        (
            "targets = ['relative/path']",
            "scanners = ['nmap']",
            "interval_hours = 0",
            "semgrep_config = '--evil'",
            "nonsense = 1",
        )
    ):
        c = start(tmp_path / f"d{i}", bad)
        try:
            assert c.run("module", "show", {"id": "scanner"}, actor="t")["status"] == "failed"
        finally:
            c.close()
    c = start(tmp_path / "ok", "")
    try:
        with pytest.raises(SignalboxError, match="no targets"):
            sc(c, "run_now")
        for action in ("run_now", "findings"):
            with pytest.raises(SignalboxError, match="read-only"):
                sc(c, action, actor="hermes")
        with pytest.raises(SignalboxError):
            sc(c, "findings", state="weird")
        assert "scanner.scan" in c.scheduler.ids()
    finally:
        c.close()


def test_review_regressions(core: Core, fakes: Path, tmp_path: Path) -> None:
    import threading

    # gitleaks exits 1 on fatal errors too: no JSON means failure, not an all-clear
    sc(core, "run_now")
    fake_tool(fakes, "gitleaks", None, code=1, text="")
    sc(core, "run_now")
    rules = {f["rule"] for f in sc(core, "findings", limit=1000)["findings"]}
    assert "gitleaks:failed" in rules and "aws-access-token" in rules  # earlier findings stay open
    # non-UTF-8 output decodes leniently; too many findings is a failure that resolves nothing
    many = tmp_path / "many.json"
    many.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "check_id": f"r{i}",
                        "path": "a.py",
                        "start": {"line": i},
                        "extra": {"severity": "INFO", "message": "secret=hunter2"},
                    }
                    for i in range(2500)
                ]
            }
        ),
        encoding="utf-8",
    )
    fake_tool(fakes, "semgrep", many, code=1)
    sc(core, "run_now")
    failed = {f["rule"]: f for f in sc(core, "findings", limit=1000)["findings"] if f["scanner"] == "scanner"}
    assert "truncated" in failed["semgrep:failed"]["title"]
    assert [
        f for f in sc(core, "findings", limit=1000)["findings"] if f["scanner"] == "semgrep"
    ]  # not resolved
    # semgrep titles never carry the message (it can interpolate matched values)
    assert all("hunter2" not in str(f) for f in sc(core, "findings", state="all", limit=1000)["findings"])
    # scanners removed from config are resolved, not left open forever
    inst = core.manager._entry("scanner").instance
    inst.settings["scanners"] = ["bandit"]
    sc(core, "run_now")
    assert not [
        f for f in sc(core, "findings", limit=1000)["findings"] if f["scanner"] in ("semgrep", "trivy")
    ]
    # one scan at a time
    inst._scanning.acquire()
    try:
        assert sc(core, "run_now") == {"skipped": "a scan is already running"}
    finally:
        inst._scanning.release()
    t = threading.Thread(target=inst.scan_all)
    t.start()
    t.join(60)
    # control characters from repository text never reach announcements
    assert parsers.clean("pkg\x1b[31m\nname", 50) == "pkg [31m name"


def test_process_broker_bounds(core: Core, tmp_path: Path, fakes: Path) -> None:
    import time

    script = tmp_path / "slow.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "sys.stdout.buffer.write(b'caf\\xe9 ' + b'x' * 5000)\nsys.stdout.flush()\n"
        "time.sleep(float(sys.argv[1]))\n",
        encoding="utf-8",
    )
    # 1.1 H1 B-10: the scanner may only run its listed programs by bare name, so the slow script stands in
    # for one of them (bandit) on PATH, the way the other fakes do.
    if os.name == "nt":
        (fakes / "bandit.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = fakes / "bandit"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    spawn = core.manager._entry("scanner").instance.ctx.spawn
    started = time.monotonic()
    with pytest.raises(SignalboxError, match="timed out"):
        spawn.run(["bandit", "30"], timeout=1)
    assert time.monotonic() - started < 15  # a grandchild holding output no longer blocks the timeout
    done = spawn.run(["bandit", "0"], timeout=20, max_output=100)
    assert done.stdout.startswith("caf\ufffd") and len(done.stdout) == 100 and done.truncated
