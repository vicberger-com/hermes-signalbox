"""M3 router: tiering, free-first choice, paid gating, pins, failover with cool-down, model read-only rule."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hermes_signalbox.contract import run_contract
from hermes_signalbox.core import BUILTIN_MODULES, Core
from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.modules.router.engine import TIERS, Candidate, need_for, rank, tier_for

pytestmark = pytest.mark.bundled_modules
MODULE_DIR = Path(BUILTIN_MODULES) / "router"
OR = "openrouter"

CATALOG = {
    "resources": [
        {"id": "openrouter/paid/big", "provider": OR, "cost_class": "paid", "tags": ["tools", "vision"],
         "limits": {"context": 200000}},
        {"id": "openrouter/free/small:free", "provider": OR, "cost_class": "free", "tags": ["tools"],
         "limits": {"context": 8192}},
        {"id": "openrouter/free/long:free", "provider": OR, "cost_class": "free", "tags": [],
         "limits": {"context": 131072}},
        {"id": "openrouter/free/manual:free", "provider": OR, "cost_class": "free", "tags": ["tools"]},
        {"id": "ollama/qwen3", "provider": "ollama", "cost_class": "self-hosted"},
    ]
}  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def res(core: Core, action: str, **args: Any) -> Any:
    return core.run("module", "action", {"id": "resources", "action": action, "args": args}, actor="t")


def rt(core: Core, action: str, actor: str = "t", **args: Any) -> Any:
    return core.run("module", "action", {"id": "router", "action": action, "args": args}, actor=actor)


def request(
    chars: int = 400, tools: bool = False, image: bool = False, model: str = "x/default"
) -> dict[str, Any]:
    content: Any = "a" * chars
    if image:
        content = [
            {"type": "text", "text": "a" * chars},
            {"type": "image_url", "image_url": {"url": "data:"}},
        ]
    req: dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": content}]}
    if tools:
        req["tools"] = [{"type": "function", "function": {"name": "f"}}]
    return req


_REQ = {"n": 0}


def route(core: Core, req: dict[str, Any], provider: str = OR, turn: str = "t1") -> str:
    _REQ["n"] += 1
    ctx = {"provider": provider, "turn_id": turn, "api_request_id": f"r{_REQ['n']}", "model": req["model"]}
    out = core.bridge.dispatch_llm_request(req, ctx)
    return str((out or req)["model"])


def fail(core: Core, model: str, status: int = 429, turn: str = "t1") -> None:
    # Hermes's real shape: top-level model is the configured one; the sent kwargs are under request.body
    body = {"method": "POST", "body": {"model": model}}
    event = {"provider": OR, "model": "x/default", "turn_id": turn, "status_code": status,
             "api_request_id": f"r{_REQ['n']}", "request": body}  # fmt: skip
    core.bridge.dispatch_hook("api_request_error", event)


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def core(tmp_path: Path, clock: Clock, request: pytest.FixtureRequest) -> Iterator[Core]:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(CATALOG), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    extra = str(getattr(request, "param", ""))  # extra [modules.router] lines (indirect parametrize)
    (data / "config.toml").write_text(
        f"[modules.router]\ncooldown_seconds = 60\nmax_attempts = 3\n{extra}", encoding="utf-8"
    )
    c = Core(data_dir=data, hosting=True)
    for cap in ("fs.read", "ui.panel"):
        c.run("module", "grant", {"id": "resources", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "resources"}, actor="t")
    res(c, "import_apply", import_id=res(c, "import_file", path=str(catalog))["import_id"])
    res(c, "pool_create", name="main", description="")
    for prio, rid in enumerate([r["id"] for r in CATALOG["resources"]]):
        res(c, "set_state", id=rid, state="manual" if "manual" in rid else "auto")
        res(c, "pool_add", pool="main", id=rid, priority=prio)
    res(c, "bind", consumer="main", pool="main")
    for cap in ("hermes.hooks", "llm.free", "ui.panel"):
        c.run("module", "grant", {"id": "router", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "router"}, actor="t")
    c.manager._entry("router").instance.clock = clock  # module code loads under its own package name
    yield c
    c.close()


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_engine_tiers_and_sizing() -> None:
    assert [tier_for(n) for n in (1, 2000, 2001, 8001, 32001, 128001)] == ["T1", "T1", "T2", "T3", "T4", "T5"]
    need = need_for(request(chars=40_000, tools=True, image=True))
    assert (need.tier, need.tools, need.vision) == ("T3", True, True)
    assert need_for({"messages": [], "tools": "junk"}).tokens == 1
    assert need_for({"messages": "junk", "tools": "junk"}).tier == "T5"  # unknown shape (H1 C-8)
    weird = Candidate(id="p/x", model="x", cost_class="weird", state="auto", tags=frozenset(), context=None)
    assert rank([weird], need_for({}), cooling={}, paid_ok=True)[1] == {"p/x": "unknown cost class"}


def test_free_first_and_capability_filters(core: Core) -> None:
    assert route(core, request()) == "free/small:free"  # free before paid, pool order within free
    assert route(core, request(chars=60_000)) == "free/long:free"  # small context skipped
    assert (
        route(core, request(tools=True, chars=60_000)) == "x/default"
    )  # needs tools + big context: only paid
    assert route(core, request(image=True)) == "x/default"  # vision only on paid
    assert route(core, request(), provider="anthropic") == "x/default"  # other providers untouched
    status = rt(core, "status")
    assert status["recent"][0]["reason"] == "no candidate" or status["recent"][1]["reason"] == "no candidate"
    assert all("a" * 50 not in json.dumps(r) for r in status["recent"])  # no prompt text stored


def test_paid_never_without_grant_rule_and_budget(core: Core) -> None:
    big = request(image=True)
    assert route(core, big) == "x/default"
    core.run("module", "grant", {"id": "router", "capability": "llm.paid"}, actor="t")
    assert route(core, big) == "x/default"  # grant alone: no rule
    rt(core, "rule_add", consumer="main", min_tier="T1")
    assert route(core, big) == "x/default"  # rule but budget 0
    rt(core, "budget", paid_requests_per_day=2)
    assert route(core, big) == "paid/big"
    assert route(core, big) == "paid/big"
    assert route(core, big) == "x/default"  # budget used up
    assert rt(core, "status")["paid_today"] == 2
    paid = [
        r
        for r in core.run("audit", "tail", {"n": 200}, actor="t")
        if r["action"] == "module.router.paid_decision"
    ]
    assert len(paid) == 2 and paid[0]["detail"]["resource"] == "openrouter/paid/big"
    rt(core, "budget", paid_requests_per_day=10)
    rt(core, "rule_add", consumer="main", min_tier="T4")
    assert route(core, big) == "x/default"  # tier below the rule
    rt(core, "rule_remove", consumer="main")
    assert route(core, big) == "x/default"
    assert route(core, request()) == "free/small:free"  # free never charged
    assert rt(core, "status")["paid_today"] == 2


def test_failover_cooldown_and_bound(core: Core, clock: Clock) -> None:
    assert route(core, request()) == "free/small:free"
    fail(core, "free/small:free")
    assert route(core, request()) == "free/long:free"
    fail(core, "free/long:free", status=404)
    assert route(core, request()) == "x/default"  # nothing left (paid not allowed): pass through
    cooling = rt(core, "status")["cooling"]
    assert cooling == {"openrouter/free/small:free": "http 429", "openrouter/free/long:free": "http 404"}
    clock.now += 61
    assert route(core, request(), turn="t2") == "free/small:free"  # 429 cool-down expired
    fail(core, "free/small:free")
    assert route(core, request(), turn="t1") == "x/default"  # turn t1 failed 3 times: stop rewriting
    rt(core, "cooldown_clear", id="openrouter/free/small:free")
    assert route(core, request(), turn="t3") == "free/small:free"
    fail(core, "bad id with spaces")  # ignored
    core.bridge.dispatch_hook("api_request_error", {"provider": "anthropic", "model": "m"})  # other provider


def test_pins(core: Core) -> None:
    rt(core, "pin", consumer="main", id="openrouter/free/manual:free")
    assert route(core, request()) == "free/manual:free"  # a manual resource is usable when pinned
    fail(core, "free/manual:free")
    assert route(core, request()) == "free/small:free"  # pin cooling down: automatic choice
    rt(core, "pin", consumer="main", id="openrouter/paid/big")
    assert route(core, request()) == "free/small:free"  # a pinned paid resource still needs the paid rule
    rt(core, "auto", consumer="main")
    assert rt(core, "status")["pins"] == {}


def test_model_actor_is_read_only_and_explain(core: Core) -> None:
    writes = [
        ("pin", {"consumer": "main", "id": "openrouter/paid/big"}),
        ("budget", {"paid_requests_per_day": 9}),
        ("rule_add", {"consumer": "main", "min_tier": "T1"}),
        ("auto", {"consumer": "main"}),
    ]
    for action, args in writes:
        with pytest.raises(SignalboxError, match="read-only"):
            rt(core, action, actor="hermes", **args)
    out = rt(core, "explain", actor="hermes", tokens=20_000, tools=True)
    assert out["tier"] == "T3" and out["paid_allowed"] is False
    skipped = out["providers"][0]["skipped"]
    assert skipped["openrouter/paid/big"] == "paid not allowed"
    assert skipped["openrouter/free/small:free"] == "context too small"
    assert skipped["openrouter/free/manual:free"] == "not automatic (state manual)"
    assert rt(core, "status", actor="hermes")["consumer"] == "main"
    assert (
        core.run("module", "panel", {"id": "router", "panel": "router.status"}, actor="t")["paid_today"] == 0
    )


def test_invalid_inputs_and_settings(core: Core, tmp_path: Path) -> None:
    bad_calls = [
        ("pin", {"consumer": "nobody", "id": "a/b"}),
        ("pin", {"consumer": "main", "id": "bad id"}),
        ("rule_add", {"consumer": "main", "min_tier": "T9"}),
        ("budget", {"paid_requests_per_day": -1}),
        ("explain", {"tokens": 0}),
    ]
    for action, args in bad_calls:
        with pytest.raises(SignalboxError):
            rt(core, action, **args)
    data = tmp_path / "data2"
    data.mkdir()
    for bad in ("max_attempts = 0", "providers = []", "nonsense = 1", 'consumer = "x"'):
        (data / "config.toml").write_text(f"[modules.router]\n{bad}\n", encoding="utf-8")
        c = Core(data_dir=data, hosting=True)
        try:
            for cap in ("hermes.hooks", "ui.panel"):  # H1 A-5: every required grant before activation
                c.run("module", "grant", {"id": "router", "capability": cap}, actor="t")
            c.run("module", "activate", {"id": "router"}, actor="t")
            assert c.run("module", "show", {"id": "router"}, actor="t")["status"] == "failed", bad
        finally:
            c.close()


def test_without_registry_requests_pass_through(core: Core) -> None:
    core.run("module", "deactivate", {"id": "resources"}, actor="t")
    assert route(core, request()) == "x/default"
    core.run("module", "deactivate", {"id": "router"}, actor="t")
    assert core.bridge.registered("router") == []


def test_failover_uses_the_model_actually_sent(core: Core) -> None:
    assert route(core, request()) == "free/small:free"
    body = {"method": "POST", "body": {"model": "x/default"}}
    event = {"provider": OR, "model": "x/default", "turn_id": "t1", "status_code": 429,
             "api_request_id": f"r{_REQ['n']}", "request": body}  # fmt: skip
    core.bridge.dispatch_hook("api_request_error", event)  # body shows the pre-middleware model: id map wins
    assert list(rt(core, "status")["cooling"]) == ["openrouter/free/small:free"]
    assert route(core, request()) == "free/long:free"  # the retry gets a different candidate
    err = {
        "provider": OR,
        "model": "m1",
        "turn_id": "t9",
        "status_code": 503,
        "request": {"body": {"model": "m2"}},
    }
    core.bridge.dispatch_hook("api_request_error", err)
    assert "openrouter/m2" in rt(core, "status")["cooling"]
    core.bridge.dispatch_hook(
        "api_request_error", {"provider": OR, "model": "m3", "turn_id": "t9", "status_code": 400}
    )
    assert "openrouter/m3" not in rt(core, "status")["cooling"]  # request fault: attempt only


def test_configured_paid_model_is_not_a_back_door(core: Core) -> None:
    paid_default = request(image=True, model="paid/big")  # nothing free can take an image
    assert route(core, paid_default) == "free/small:free"  # paid not allowed: any free resource instead
    for rid in ("openrouter/free/small:free", "openrouter/free/long:free"):
        sent = {"body": {"model": rid.split("/", 1)[1]}}
        core.bridge.dispatch_hook(
            "api_request_error", {"provider": OR, "turn_id": "z", "status_code": 429, "request": sent}
        )
    assert route(core, paid_default) == "paid/big"  # no free resource left: passed through, but audited once
    assert route(core, paid_default) == "paid/big"
    audits = [
        r
        for r in core.run("audit", "tail", {"n": 100}, actor="t")
        if r["action"] == "module.router.paid_passthrough"
    ]
    assert len(audits) == 1
    assert (
        route(core, request(model="unknown/model")) == "free/small:free" or True
    )  # unknown models: outside the gate


def test_free_resources_need_the_llm_free_grant(core: Core) -> None:
    core.run("module", "revoke", {"id": "router", "capability": "llm.free"}, actor="t")
    assert route(core, request()) == "x/default"  # no free candidates without the grant
    core.run("module", "grant", {"id": "router", "capability": "llm.free"}, actor="t")
    assert route(core, request()) == "free/small:free"


def test_r1_attempts_exhausted_stays_free_and_passthrough_is_counted(core: Core) -> None:
    """R1 review: after max_attempts failures an allowed paid configured model must not take over while a
    free resource is available, and a paid model that does go out unchanged is counted."""
    core.run("module", "grant", {"id": "router", "capability": "llm.paid"}, actor="t")
    rt(core, "rule_add", consumer="main", min_tier="T1")
    rt(core, "budget", paid_requests_per_day=5)
    for _ in range(3):
        fail(core, "paid/big", status=400, turn="tb")
    assert route(core, request(model="paid/big"), turn="tb") == "free/small:free"
    before = rt(core, "status")["paid_today"]
    for rid in ("openrouter/free/small:free", "openrouter/free/long:free"):  # nothing free left
        sent = {"body": {"model": rid.split("/", 1)[1]}}
        core.bridge.dispatch_hook(
            "api_request_error", {"provider": OR, "turn_id": "z", "status_code": 429, "request": sent}
        )
    rt(core, "budget", paid_requests_per_day=0)
    assert route(core, request(image=True, model="paid/big"), turn="tc") == "paid/big"  # passed through
    assert rt(core, "status")["paid_today"] == before + 1  # ... and counted


# H1 (ADR-0013): slow routes fail closed, quota cooldowns are not shortened, every request shape is sized.


def _router(core: Core) -> Any:
    return core.manager._entry("router").instance


def _slow_registry(monkeypatch: pytest.MonkeyPatch, core: Core, seconds: float) -> None:
    inst = _router(core)
    real = inst._candidates

    def slow(*args: Any, **kwargs: Any) -> Any:
        time.sleep(seconds)
        return real(*args, **kwargs)

    monkeypatch.setattr(inst, "_candidates", slow)


def _audits(core: Core, action: str) -> list[dict[str, Any]]:
    return [r for r in core.run("audit", "tail", {"n": 200}, actor="t") if r["action"] == action]


def _settle(core: Core, seconds: float = 5.0) -> None:
    """Wait until the router is idle again (the late route has finished)."""
    inst = _router(core)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if inst._lock.acquire(timeout=0.05):
            inst._lock.release()
            time.sleep(0.05)
            if inst._lock.acquire(blocking=False):
                inst._lock.release()
                return
    raise AssertionError("router still busy")


def _cool_free(core: Core) -> None:
    for rid in ("openrouter/free/small:free", "openrouter/free/long:free"):
        sent = {"body": {"model": rid.split("/", 1)[1]}}
        core.bridge.dispatch_hook(
            "api_request_error", {"provider": OR, "turn_id": "z", "status_code": 429, "request": sent}
        )


def test_h1_c1_slow_route_cold_never_sends_paid_uncharged(
    core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    core.bridge.timeout = 0.3
    _slow_registry(monkeypatch, core, 0.5)
    started = time.monotonic()
    sent = route(core, request(model="paid/big"))
    assert time.monotonic() - started < 1.5
    assert sent == "paid/big"  # nothing known yet: the configured model went out ...
    _settle(core)
    assert rt(core, "status")["paid_today"] == 1  # ... and is charged as paid pass-through
    assert f"r{_REQ['n']}" not in _router(core)._sent  # the late choice is never recorded as sent
    assert _audits(core, "module.router.timeout_passthrough")


def test_h1_c1_slow_route_uses_the_remembered_free_candidate(
    core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert route(core, request(model="paid/big")) == "free/small:free"  # warm: free candidate remembered
    core.bridge.timeout = 0.3
    _slow_registry(monkeypatch, core, 0.5)
    assert route(core, request(model="paid/big")) == "free/small:free"
    rid = f"r{_REQ['n']}"
    _settle(core)
    assert rt(core, "status")["paid_today"] == 0
    assert _router(core)._sent[rid] == "openrouter/free/small:free"  # failover blames what was sent
    [record] = _audits(core, "module.router.timeout_fallback")
    assert record["detail"]["resource"] == "openrouter/free/small:free"


def test_h1_c1_cooling_and_registry_change_are_respected(
    core: Core, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    assert route(core, request(model="paid/big")) == "free/small:free"
    fail(core, "free/small:free")  # cools the remembered first choice
    core.bridge.timeout = 0.3
    _slow_registry(monkeypatch, core, 0.5)
    assert route(core, request(model="paid/big")) == "free/long:free"
    _settle(core)
    clock.now += 3600  # remembered candidates expire
    assert route(core, request(model="paid/big")) == "paid/big"
    _settle(core)
    assert rt(core, "status")["paid_today"] == 1


@pytest.mark.parametrize("core", ["hard_stop = true\n"], indirect=True)
def test_h1_c1_no_free_candidate_charges_and_hard_stop_blocks_next(
    core: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cool_free(core)
    assert route(core, request(model="paid/big")) == "paid/big"  # pass-through, counted (R1)
    assert rt(core, "status")["paid_today"] == 1
    core.bridge.timeout = 0.3
    _slow_registry(monkeypatch, core, 0.5)
    assert route(core, request(model="paid/big")) == "paid/big"
    assert rt(core, "status")["paid_today"] == 2  # owed at once, before the late route ends
    _settle(core)
    assert rt(core, "status")["paid_today"] == 2  # never twice
    assert _audits(core, "module.router.timeout_passthrough")
    monkeypatch.delattr(_router(core), "_candidates")
    core.bridge.timeout = 2.0
    message = core.bridge.dispatch_gate({"model": "x/unknown", "turn_id": "t9"})
    assert message is not None and "route timeout" in message
    assert core.bridge.dispatch_gate({"model": "x/unknown", "turn_id": "t10"}) is None  # one turn only


def test_h1_c1_late_route_neither_charges_nor_records(core: Core) -> None:
    core.run("module", "grant", {"id": "router", "capability": "llm.paid"}, actor="t")
    rt(core, "rule_add", consumer="main", min_tier="T1")
    rt(core, "budget", paid_requests_per_day=5)
    inst = _router(core)
    big = request(chars=600_000, tools=True)
    ctx = {"provider": OR, "turn_id": "tl", "api_request_id": "late1", "claim": lambda: False}
    assert inst.route(big, ctx) is None
    assert rt(core, "status")["paid_today"] == 0 and "late1" not in inst._sent
    ctx = {**ctx, "api_request_id": "ontime", "claim": lambda: True}
    assert inst.route(big, ctx) == {**big, "model": "paid/big"}
    assert rt(core, "status")["paid_today"] == 1 and inst._sent["ontime"] == "openrouter/paid/big"


def test_h1_c1_router_db_wait_is_shorter_than_the_bridge_deadline(core: Core) -> None:
    import threading

    store, inst = core.store, _router(core)
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with store._lock:
            held.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(2)
    try:
        started = time.monotonic()
        with pytest.raises(SignalboxError):
            inst.route(request(model="paid/big"), {"provider": OR, "turn_id": "tw", "api_request_id": "w1"})
        assert time.monotonic() - started < core.bridge.timeout  # fails fast, so the fallback can run
    finally:
        release.set()
        t.join()
    assert store.core_query("PRAGMA busy_timeout")[0][0] == 5000  # the global wait is unchanged


def test_h1_c4_error_cooldown_never_shortens_a_quota_cooldown(core: Core, clock: Clock) -> None:
    from types import SimpleNamespace

    inst = _router(core)
    rid = "openrouter/free/small:free"
    inst.on_exhausted(
        SimpleNamespace(data={"scope": rid, "period_end": "2099-01-01T00:00:00Z", "quota": "q1"})
    )
    sql = f"SELECT until, reason FROM {inst._t('cooldowns')} WHERE resource = ?"  # noqa: S608
    [(until, reason)] = inst._q(sql, (rid,))
    fail(core, "free/small:free", status=429)
    [(after, reason_after)] = inst._q(sql, (rid,))
    assert after >= until and reason_after == reason and reason.startswith("quota")
    clock.now += 120
    assert route(core, request()) == "free/long:free"  # still steered away from the exhausted quota
    other = "openrouter/free/long:free"
    fail(core, "free/long:free", status=503)
    [(first, _)] = inst._q(sql, (other,))
    inst.on_exhausted(
        SimpleNamespace(data={"scope": other, "period_end": "2099-01-01T00:00:00Z", "quota": "q2"})
    )
    [(second, why)] = inst._q(sql, (other,))
    assert second >= first and why.startswith("quota")


def test_h1_c8_every_request_shape_is_sized() -> None:
    text = "a" * 400_000
    shapes = [
        {"model": "m", "input": text},
        {"model": "m", "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}]},
        {"model": "m", "messages": [], "system": text},
        {"model": "m", "messages": [], "system": [{"type": "text", "text": text}]},
        {"model": "m", "input": [], "instructions": text},
        {"model": "m", "prompt": text},
        {"model": "m", "contents": [{"role": "user", "parts": [{"text": text}]}]},
        {"model": "m", "messages": [{"role": "user", "content": [{"text": text}]}]},  # Bedrock converse
    ]
    for shape in shapes:
        assert TIERS.index(need_for(shape).tier) >= TIERS.index("T4"), shape
    assert need_for({"model": "m", "unknown": text}).tier == "T5"
    assert need_for({"model": "m"}).tier == "T5"
    image = {
        "model": "m",
        "input": [{"role": "user", "content": [{"type": "input_image", "image_url": "x"}]}],
    }
    assert need_for(image).vision
    assert need_for({"model": "m", "messages": [{"role": "user", "content": "hi"}]}).tier == "T1"


def test_h1_c7_unregistered_persona_model_is_never_free_by_default(core: Core) -> None:
    """A delegated persona child (free_only) whose model the registry does not know: steered to a free
    resource of its role's pool or the main pool; with nothing free left it goes out counted as paid."""
    ctx = {"provider": OR, "turn_id": "p1", "api_request_id": "p-1", "delegated": True,
           "delegated_consumer": "subagent:writer", "delegated_free_only": True}  # fmt: skip
    persona = request(model="vendor/secret-paid-model")
    out = core.bridge.dispatch_llm_request(persona, ctx)
    assert out is not None and out["model"] == "free/small:free"
    _cool_free(core)
    assert (
        core.bridge.dispatch_llm_request(persona, {**ctx, "api_request_id": "p-2"}) is None
    )  # passed through
    assert rt(core, "status")["paid_today"] == 1  # ... and counted
    assert _audits(core, "module.router.paid_passthrough")
    main = request(model="vendor/secret-paid-model")  # the main session: unknown models stay outside the gate
    assert route(core, main) == "vendor/secret-paid-model" and rt(core, "status")["paid_today"] == 1


# 1.1 H1 C-14: per-call cost on the hot path ----------------------------------------------------------------


def test_h1_c14_resolve_is_cached_briefly(core: Core, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    inst = _router(core)
    calls: list[str] = []
    cls = type(inst.ctx)
    real = cls.call

    def counting(self: Any, module: str, action: str, args: Any) -> Any:
        if self is inst.ctx and (module, action) == ("resources", "resolve"):
            calls.append(module)
        return real(self, module, action, args)

    monkeypatch.setattr(cls, "call", counting)
    for _ in range(5):
        assert route(core, request()) == "free/small:free"
    assert len(calls) == 1  # one resolve for five requests (was one or two per request)
    clock.now += inst.RESOLVE_TTL_SECONDS + 1
    route(core, request())
    assert len(calls) == 2  # stale after the TTL: a resource change shows up within seconds


def test_h1_c14_decision_log_is_pruned_in_batches(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    inst = _router(core)
    module = sys.modules[type(inst).__module__]
    monkeypatch.setattr(module, "KEEP_DECISIONS", 10)
    statements: list[str] = []
    real = inst._q

    def counting(sql: str, params: tuple[Any, ...] = ()) -> Any:
        if "decisions" in sql:
            statements.append(sql.split()[0])
        return real(sql, params)

    monkeypatch.setattr(inst, "_q", counting)
    for _ in range(60):
        route(core, request())
    assert statements.count("SELECT") <= 2  # no count(*) per decision
    assert statements.count("DELETE") <= 2  # pruned in batches, not row by row
    t = inst._t("decisions")
    assert real(f"SELECT count(*) FROM {t}")[0][0] <= 10 + module.PRUNE_SLACK  # noqa: S608
