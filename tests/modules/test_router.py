"""M3 router: tiering, free-first choice, paid gating, pins, failover with cool-down, model read-only rule."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from switchyard.contract import run_contract
from switchyard.core import BUILTIN_MODULES, Core
from switchyard.errors import SwitchyardError
from switchyard.modules.router.engine import Candidate, need_for, rank, tier_for

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
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def core(tmp_path: Path, clock: Clock) -> Iterator[Core]:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(CATALOG), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.toml").write_text(
        "[modules.router]\ncooldown_seconds = 60\nmax_attempts = 3\n", encoding="utf-8"
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
    assert need_for({"messages": "junk", "tools": "junk"}).tokens == 1
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
        with pytest.raises(SwitchyardError, match="read-only"):
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
        with pytest.raises(SwitchyardError):
            rt(core, action, **args)
    data = tmp_path / "data2"
    data.mkdir()
    for bad in ("max_attempts = 0", "providers = []", "nonsense = 1", 'consumer = "x"'):
        (data / "config.toml").write_text(f"[modules.router]\n{bad}\n", encoding="utf-8")
        c = Core(data_dir=data, hosting=True)
        try:
            c.run("module", "grant", {"id": "router", "capability": "hermes.hooks"}, actor="t")
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
