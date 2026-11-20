"""M6 supervisor: schedule broker, core view, findings lifecycle, alerts, soak, restart; router hard stop."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from switchyard.contract import run_contract
from switchyard.core import BUILTIN_MODULES, Core
from switchyard.errors import SwitchyardError

pytestmark = pytest.mark.bundled_modules
MODULE_DIR = Path(BUILTIN_MODULES) / "supervisor"
OR = "openrouter"


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def sv(core: Core, action: str, actor: str = "t", **args: Any) -> Any:
    return core.run("module", "action", {"id": "supervisor", "action": action, "args": args}, actor=actor)


def mt(core: Core, action: str, **args: Any) -> Any:
    return core.run("module", "action", {"id": "meter", "action": action, "args": args}, actor="t")


def grant(core: Core, module: str, *caps: str) -> None:
    for cap in caps:
        core.run("module", "grant", {"id": module, "capability": cap}, actor="t")


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes"))


@pytest.fixture
def clock() -> Clock:
    return Clock()


def start(data: Path, clock: Clock) -> Core:
    c = Core(data_dir=data, hosting=True)
    grant(c, "supervisor", "schedule", "core.read", "ui.panel")
    c.run("module", "activate", {"id": "supervisor"}, actor="t")
    c.manager._entry("supervisor").instance.clock = clock
    return c


@pytest.fixture
def core(tmp_path: Path, clock: Clock) -> Iterator[Core]:
    c = start(tmp_path / "data", clock)
    yield c
    c.close()


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_runs_on_the_core_schedule(core: Core) -> None:
    assert "supervisor.checks" in core.scheduler.ids()
    core.scheduler.fire("supervisor.checks")
    assert sv(core, "report")["last_run"] is not None and sv(core, "report")["llm_calls"] == 0
    core.run("module", "deactivate", {"id": "supervisor"}, actor="t")
    assert "supervisor.checks" not in core.scheduler.ids()


def test_findings_open_escalate_ack_and_resolve(core: Core) -> None:
    alerts: list[Any] = []
    core.bus.subscribe("test", "supervisor.alert", alerts.append)
    grant(core, "meter", "hermes.hooks", "ui.panel")
    core.run("module", "activate", {"id": "meter"}, actor="t")
    mt(core, "quota_add", name="day", scope="all", metric="requests", period="day", limit="10")

    def responses(n: int) -> None:
        for _ in range(n):
            core.bridge.dispatch_hook(
                "post_api_request",
                {"provider": OR, "model": "m/x", "usage": {"input_tokens": 1, "output_tokens": 1}},
            )

    responses(8)
    out = sv(core, "run_now")
    assert out["new"] == 1 and alerts == []  # medium: listed, no alert
    sv(core, "ack", key="quota:day")
    assert sv(core, "findings", state="acked")["findings"][0]["key"] == "quota:day"
    sv(core, "run_now")
    assert sv(core, "findings", state="acked")["findings"][0]["count"] == 2  # still acked
    responses(2)
    sv(core, "run_now")  # exhausted: escalates to high, re-opens, alerts
    assert [a.data["key"] for a in alerts] == ["quota:day"]
    assert sv(core, "findings")["findings"][0]["severity"] == "high"
    mt(core, "quota_remove", name="day")
    sv(core, "run_now")
    assert (
        sv(core, "report")["open"] == []
        and sv(core, "findings", state="resolved")["findings"][0]["key"] == "quota:day"
    )
    with pytest.raises(SwitchyardError, match="no open finding"):
        sv(core, "ack", key="quota:day")


def test_failed_modules_audit_chain_and_isolated_checks(
    core: Core, tmp_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    grant(core, "router", "hermes.hooks")
    grant(core, "router", "ui.panel")  # every required grant: the bad setting is what fails
    data = core.data_dir
    (data / "config.toml").write_text("[modules.router]\nmax_attempts = 0\n", encoding="utf-8")
    core.config = type(core.config)(**{**core.config.__dict__, "modules": {"router": {"max_attempts": 0}}})
    core.run("module", "activate", {"id": "router"}, actor="t")
    sv(core, "run_now")
    keys = {f["key"] for f in sv(core, "findings")["findings"]}
    assert "module:router:failed" in keys
    view = core.manager._entry("supervisor").instance.ctx.core._facade
    monkeypatch.setattr(
        view, "verify_audit", lambda: {"ok": False, "records": 9, "first_bad_seq": 4, "reason": "hash"}
    )
    sv(core, "run_now")  # audit already checked at activation time: not due yet
    assert "audit:chain" not in {f["key"] for f in sv(core, "findings")["findings"]}
    clock.now += 25 * 3600
    sv(core, "run_now")
    finding = next(f for f in sv(core, "findings")["findings"] if f["key"] == "audit:chain")
    assert finding["severity"] == "critical" and "record 4" in finding["message"]
    sv(core, "run_now")  # not due: the last result is kept
    assert "audit:chain" in {f["key"] for f in sv(core, "findings")["findings"]}
    monkeypatch.setattr(view, "modules", lambda: 1 / 0)
    out = sv(core, "run_now")
    assert out["errors"] == 1 and "supervisor:check:modules" in {
        f["key"] for f in sv(core, "findings")["findings"]
    }


def test_soak_stays_bounded_and_survives_restart(tmp_path: Path, clock: Clock) -> None:
    data = tmp_path / "data"
    c = start(data, clock)
    try:
        inst = c.manager._entry("supervisor").instance
        flip = {"n": 0}

        def churn() -> list[tuple[str, str, str]]:
            flip["n"] += 1
            return [(f"churn:{flip['n']}", "low", "transient")]  # a new finding every run, resolved next run

        inst._check_router = churn
        inst.run_checks.__globals__.update(KEEP_RUNS=50, KEEP_RESOLVED=50)  # small bounds keep the soak fast
        for _ in range(200):
            clock.now += 300
            inst.run_checks()
        t = inst.ctx.state.table
        runs = inst._q(f"SELECT count(*) FROM {t('runs')}")[0][0]  # noqa: S608
        findings = inst._q(f"SELECT count(*) FROM {t('findings')}")[0][0]  # noqa: S608
        assert runs <= 50 and findings <= 52
        last_audit = inst._last_audit_check
    finally:
        c.close()
    c = start(data, clock)  # restart: state and the audit-check time come back
    try:
        inst = c.manager._entry("supervisor").instance
        assert inst._last_audit_check == last_audit
        assert sv(c, "report")["last_run"] is not None
    finally:
        c.close()


def test_model_is_read_only_and_settings(core: Core, tmp_path: Path) -> None:
    for action, args in [("ack", {"key": "x"}), ("run_now", {})]:
        with pytest.raises(SwitchyardError, match="read-only"):
            sv(core, action, actor="hermes", **args)
    assert sv(core, "report", actor="hermes")["llm_calls"] == 0
    with pytest.raises(SwitchyardError):
        sv(core, "findings", state="weird")
    assert (
        core.run("module", "panel", {"id": "supervisor", "panel": "supervisor.status"}, actor="t")["open"]
        == []
    )
    with pytest.raises(SwitchyardError, match=r"llm\.paid"):
        core.run("module", "grant", {"id": "supervisor", "capability": "llm.paid"}, actor="t")
    data = tmp_path / "d2"
    data.mkdir()
    for bad in ("interval_seconds = 5", "nonsense = 1"):
        (data / "config.toml").write_text(f"[modules.supervisor]\n{bad}\n", encoding="utf-8")
        c = Core(data_dir=data, hosting=True)
        try:
            grant(c, "supervisor", "schedule", "core.read", "ui.panel")
            c.run("module", "activate", {"id": "supervisor"}, actor="t")
            assert c.run("module", "show", {"id": "supervisor"}, actor="t")["status"] == "failed"
        finally:
            c.close()


def test_slow_jobs_do_not_stall_the_tick(core: Core) -> None:
    import threading
    import time as _time

    release = threading.Event()
    calls = {"n": 0}

    def slow() -> None:
        calls["n"] += 1
        release.wait(5)

    sched = core.manager._entry("supervisor").instance.ctx.schedule
    core.schedules.timeout = 0.2
    sched.every("slow", 60, slow)
    start = _time.monotonic()
    core.scheduler.fire("supervisor.slow")
    core.scheduler.fire("supervisor.slow")  # previous run still going: skipped, not stacked
    assert _time.monotonic() - start < 2 and calls["n"] == 1
    assert core.run("module", "list", {}, actor="t")  # control plane still answers
    assert "module.job_timeout" in [r["action"] for r in core.run("audit", "tail", {"n": 20}, actor="t")]
    release.set()


def test_schedule_broker_rules(core: Core) -> None:
    sched = core.manager._entry("supervisor").instance.ctx.schedule
    for name, seconds in [("Bad", 60), ("ok", 5), ("ok", True), ("ok", 100_000)]:
        with pytest.raises(SwitchyardError):
            sched.every(name, seconds, lambda: None)
    sched.every("extra", 60, lambda: None)
    assert "supervisor.extra" in core.scheduler.ids() and sched.stats("extra")["fired"] == 0
    sched.cancel("extra")
    assert "supervisor.extra" not in core.scheduler.ids()


def test_router_hard_stop_blocks_the_turn(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.toml").write_text("[modules.router]\nhard_stop = true\n", encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "resources": [
                    {"id": f"{OR}/paid/big", "provider": OR, "cost_class": "paid"},
                    {"id": f"{OR}/free/a:free", "provider": OR, "cost_class": "free"},
                ]
            }
        ),
        encoding="utf-8",
    )
    c = Core(data_dir=data, hosting=True)
    try:
        grant(c, "resources", "fs.read", "ui.panel")
        c.run("module", "activate", {"id": "resources"}, actor="t")

        def res(action: str, **args: Any) -> Any:
            return c.run("module", "action", {"id": "resources", "action": action, "args": args}, actor="t")

        res("import_apply", import_id=res("import_file", path=str(catalog))["import_id"])
        res("pool_create", name="main", description="")
        for i, rid in enumerate((f"{OR}/paid/big", f"{OR}/free/a:free")):
            res("set_state", id=rid, state="auto")
            res("pool_add", pool="main", id=rid, priority=i)
        res("bind", consumer="main", pool="main")
        grant(c, "router", "hermes.hooks", "ui.panel", "llm.free")
        c.run("module", "activate", {"id": "router"}, actor="t")
        # Hermes's real pre_llm_call keyword arguments: no provider (agent/turn_context.py)
        turn = {
            "session_id": "s",
            "task_id": "k",
            "turn_id": "t",
            "user_message": "hi",
            "conversation_history": [],
            "is_first_turn": True,
            "model": "paid/big",
            "platform": "cli",
            "parent_session_id": "",
            "sender_id": "u",
        }
        assert c.bridge.dispatch_gate(turn) is None  # a free model can take it
        pin = {"consumer": "main", "id": f"{OR}/free/a:free"}
        c.run("module", "action", {"id": "router", "action": "pin", "args": pin}, actor="t")
        c.bridge.dispatch_hook(
            "api_request_error",
            {
                "provider": OR,
                "status_code": 404,
                "turn_id": "x",
                "request": {"body": {"model": "free/a:free"}},
            },
        )
        reason = c.bridge.dispatch_gate(turn)
        assert reason is not None and "router module (paid model not allowed)" in reason
        assert "module.router.hard_stop" in [
            r["action"] for r in c.run("audit", "tail", {"n": 50}, actor="t")
        ]
        assert c.bridge.dispatch_gate({**turn, "model": "unknown/model"}) is None  # not a registry resource
        exhausted = type(
            "E", (), {"data": {"scope": f"provider:{OR}", "period_end": "2099-01-01T00:00:00Z", "quota": "q"}}
        )()
        c.manager._entry("router").instance.on_exhausted(exhausted)
        assert (
            c.bridge.dispatch_gate({**turn, "model": "unknown/model"}) is None
        )  # still unknown: never blocked
        assert "quota exhausted" in (c.bridge.dispatch_gate(turn) or "")
        total = type(
            "E", (), {"data": {"scope": "all", "period_end": "2099-01-01T00:00:00Z", "quota": "q"}}
        )()
        c.manager._entry("router").instance.on_exhausted(total)
        assert c.bridge.dispatch_gate({**turn, "model": "unknown/model"}) is None  # unknown: never blocked
        c.run("module", "deactivate", {"id": "resources"}, actor="t")
        assert c.bridge.dispatch_gate(turn) is None  # registry down: no positive knowledge, no block
        out = c.run("module", "revoke", {"id": "router", "capability": "hermes.hooks"}, actor="t")
        assert out["deactivated"] is True and c.bridge.registered("router") == []
        out = c.run("module", "revoke", {"id": "router", "capability": "llm.free"}, actor="t")
        assert out["deactivated"] is False  # optional capability: checked at run time
    finally:
        c.close()


def test_core_view_caches_audit_verification(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    view = core.manager._entry("supervisor").instance.ctx.core
    calls = {"n": 0}
    real = core.verify_audit

    def counted() -> Any:
        calls["n"] += 1
        return real()

    monkeypatch.setattr(core, "verify_audit", counted)
    first = view.verify_audit()
    for _ in range(20):
        assert view.verify_audit() == first
    assert calls["n"] <= 1
    assert {m["id"] for m in view.modules()} >= {"supervisor"}


def test_ack_long_key_and_audit_retry(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    inst = core.manager._entry("supervisor").instance
    inst._check_router = lambda: [("x" * 250, "low", "m")]
    sv(core, "run_now")
    assert sv(core, "ack", key="x" * 250)["acked"] == "x" * 200
    assert sv(core, "findings", state="acked")["findings"][0]["key"] == "x" * 200
    inst._last_audit_check = 0.0
    monkeypatch.setattr(inst.ctx.core._facade, "verify_audit", lambda: 1 / 0)
    sv(core, "run_now")
    assert inst._last_audit_check == 0.0  # failed verification stays due
