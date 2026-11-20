"""M4 meter: exact totals, cost estimate, thresholds once per period, forecast, no text, router reaction."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from switchyard.contract import run_contract
from switchyard.core import BUILTIN_MODULES, Core
from switchyard.errors import SwitchyardError

pytestmark = pytest.mark.bundled_modules
MODULE_DIR = Path(BUILTIN_MODULES) / "meter"
OR = "openrouter"
T0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC).timestamp()

PRICES = {
    OR: {
        "models": {
            "paid/big": {"cost": {"input": 3, "output": 15, "cache_read": 0.3}},
            "free/small:free": {"cost": {"input": 0, "output": 0}},
            "odd": {"cost": {"input": "x", "output": 1}},
            "bad id": {"cost": {"input": 1, "output": 1}},
        }
    },
    "junk": "not an object",
}


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


def mt(core: Core, action: str, actor: str = "t", **args: Any) -> Any:
    return core.run("module", "action", {"id": "meter", "action": action, "args": args}, actor=actor)


def response(core: Core, model: str, usage: Any = None, provider: str = OR, **extra: Any) -> None:
    """Replays Hermes v0.23.2's post_api_request keyword arguments (agent/turn_response_intake.py)."""
    kw = {
        "task_id": "task",
        "turn_id": "turn",
        "api_request_id": "req",
        "session_id": "s",
        "platform": "cli",
        "model": "configured/default",
        "provider": provider,
        "base_url": "https://openrouter.ai/api/v1",
        "api_mode": "chat_completions",
        "api_call_count": 1,
        "api_duration": 1.2,
        "finish_reason": "stop",
        "message_count": 3,
        "response_model": model,
        "response": {"model": model, "assistant_message": {"content": "THE ANSWER TEXT"}},
        "usage": usage,
        "assistant_message": object(),
        "assistant_content_chars": 15,
        "user_message": "THE PROMPT TEXT",
        **extra,
    }
    core.bridge.dispatch_hook("post_api_request", kw)


def usage(inp: int = 1000, out: int = 500, cache_read: int = 0) -> dict[str, int]:
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
        "request_count": 1,
        "prompt_tokens": inp + cache_read,
        "total_tokens": inp + cache_read + out,
    }


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def core(tmp_path: Path, clock: Clock) -> Iterator[Core]:
    cache = tmp_path / "models_dev_cache.json"
    cache.write_text(json.dumps(PRICES), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.toml").write_text(
        f"[modules.meter]\nmodels_dev_cache = {json.dumps(str(cache))}\n", encoding="utf-8"
    )
    c = Core(data_dir=data, hosting=True)
    for cap in ("hermes.hooks", "ui.panel", "fs.read"):
        c.run("module", "grant", {"id": "meter", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "meter"}, actor="t")
    c.manager._entry("meter").instance.clock = clock
    yield c
    c.close()


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_totals_equal_reported_usage_and_cost_estimate(core: Core) -> None:
    reported = [usage(1000, 500), usage(2000, 100, cache_read=4000), usage(7, 3)]
    for u in reported:
        response(core, "paid/big", u)
    response(core, "free/small:free", usage(50, 50))
    response(core, "unknown/model", usage(10, 10))
    response(core, "paid/big", None)  # no usage reported
    s = mt(core, "summary", days=1)
    big = next(m for m in s["models"] if m["model"] == "paid/big")
    assert big["requests"] == 4 and big["usage_missing"] == 1
    assert big["input_tokens"] == sum(u["input_tokens"] for u in reported)  # tolerance 0
    assert big["output_tokens"] == sum(u["output_tokens"] for u in reported)
    assert big["cache_read_tokens"] == 4000
    assert big["tokens"] == sum(u["total_tokens"] for u in reported)
    expected_usd = (3007 * 3 + 603 * 15 + 4000 * 0.3) / 1_000_000
    assert big["cost_usd"] == pytest.approx(expected_usd, abs=1e-6)
    unknown = next(m for m in s["models"] if m["model"] == "unknown/model")
    assert unknown["unpriced"] == 1 and unknown["cost_usd"] == 0
    assert s["totals"]["requests"] == 6
    assert mt(core, "prices_reload")["prices"] == 2  # odd/bad entries skipped


def test_meter_stores_no_text(core: Core, tmp_path: Path) -> None:
    response(core, "paid/big", usage())
    core.bridge.dispatch_hook(
        "subagent_stop",
        {
            "child_role": "leaf",
            "child_status": "completed",
            "duration_ms": 900,
            "child_summary": "THE CHILD SUMMARY",
            "tool_call_history": ["x"],
        },
    )
    core.close()
    blob = b"".join(
        p.read_bytes() for p in (tmp_path / "data").rglob("*") if p.is_file() and p.name != "host.lock"
    )
    for text in (b"THE PROMPT TEXT", b"THE ANSWER TEXT", b"THE CHILD SUMMARY"):
        assert text not in blob


def test_hostile_usage_values(core: Core) -> None:
    response(
        core,
        "paid/big",
        {
            "input_tokens": -5,
            "output_tokens": True,
            "cache_read_tokens": 10**12,
            "cache_write_tokens": 1.5,
            "reasoning_tokens": "9",
        },
    )
    response(core, "x" * 500, usage())  # truncated but still a valid key
    response(core, "bad model id", usage())  # ignored
    response(core, "paid/big", usage(), provider=None)  # ignored
    big = next(m for m in mt(core, "summary")["models"] if m["model"] == "paid/big")
    assert big["tokens"] == 0 and big["usage_missing"] == 1 and big["requests"] == 1


def test_threshold_fires_once_per_period(core: Core, clock: Clock) -> None:
    events: list[Any] = []
    core.bus.subscribe("test", "meter.*", events.append)
    mt(
        core,
        "quota_add",
        name="or-day",
        scope=f"provider:{OR}",
        metric="requests",
        period="day",
        limit="4",
        thresholds="50,100",
    )
    for _ in range(6):
        response(core, "paid/big", usage())
    kinds = [(e.type, e.data["percent"]) for e in events]
    assert kinds == [("meter.threshold", 50), ("meter.threshold", 100), ("meter.exhausted", 100)]
    assert events[-1].data["period_end"] == "2026-11-21T00:00:00Z"
    clock.now += 86_400  # next day: fires again, once
    for _ in range(3):
        response(core, "paid/big", usage())
    assert [e.data["percent"] for e in events[3:]] == [50]
    audited = [
        r for r in core.run("audit", "tail", {"n": 200}, actor="t") if r["action"] == "module.meter.threshold"
    ]
    assert len(audited) == 3
    q = mt(core, "quotas")["quotas"][0]
    assert q["used"] == 3 and q["percent"] == 75.0


def test_forecast_and_scopes(core: Core, clock: Clock) -> None:
    mt(
        core,
        "quota_add",
        name="big-cost",
        scope=f"{OR}/paid/big",
        metric="cost_usd",
        period="month",
        limit="1",
    )
    mt(core, "quota_add", name="all-tokens", scope="all", metric="tokens", period="day", limit="100000")
    for _ in range(5):
        response(core, "paid/big", usage(10_000, 1_000))  # $0.045 each
        clock.now += 3600
    fc = mt(core, "forecast", name="big-cost")
    assert fc["used"] == pytest.approx(0.225) and fc["rate_per_hour"] == pytest.approx(
        0.225 / 24
    )  # 24 h window
    assert fc["exhausted_at"] is not None and fc["period_end"] == "2026-12-01T00:00:00Z"
    tokens = mt(core, "forecast", name="all-tokens")
    assert tokens["used"] == 55_000
    with pytest.raises(SwitchyardError, match="no quota"):
        mt(core, "forecast", name="nope")
    mt(core, "quota_remove", name="big-cost")
    assert [q["name"] for q in mt(core, "quotas")["quotas"]] == ["all-tokens"]
    day = mt(core, "usage", day="2026-11-20", provider=OR)
    assert day["models"][0]["requests"] == 5


def test_errors_subagents_and_retention(core: Core, clock: Clock) -> None:
    core.bridge.dispatch_hook(
        "api_request_error",
        {
            "provider": OR,
            "model": "configured/default",
            "status_code": 429,
            "request": {"method": "POST", "body": {"model": "paid/big"}},
            "error": {"type": "RateLimit", "message": "m"},
        },
    )
    core.bridge.dispatch_hook(
        "subagent_stop", {"child_role": "leaf", "child_status": "completed", "duration_ms": 900}
    )
    core.bridge.dispatch_hook(
        "subagent_stop", {"child_role": "leaf", "child_status": "completed", "duration_ms": 100}
    )
    today = mt(core, "usage")
    assert today["models"][0]["errors"] == 1 and today["models"][0]["model"] == "paid/big"
    assert today["subagents"] == [{"role": "leaf", "status": "completed", "runs": 2, "duration_ms": 1000}]
    clock.now += 100 * 86_400
    response(core, "paid/big", usage())  # new hour: prunes rows older than retention
    assert mt(core, "usage", day="2026-11-20")["models"] == []


def test_model_cannot_change_quotas_and_bad_inputs(core: Core) -> None:
    with pytest.raises(SwitchyardError, match="read-only"):
        mt(
            core,
            "quota_add",
            actor="hermes",
            name="q",
            scope="all",
            metric="requests",
            period="day",
            limit="1",
        )
    with pytest.raises(SwitchyardError, match="read-only"):
        mt(core, "quota_remove", actor="hermes", name="q")
    assert mt(core, "summary", actor="hermes")["totals"]["requests"] == 0
    bad = [
        {"name": "Bad Name"},
        {"scope": "bad scope!"},
        {"metric": "joules"},
        {"period": "week"},
        {"limit": "0"},
        {"limit": "nan"},
        {"limit": "abc"},
        {"thresholds": "a,b"},
        {"thresholds": "0,150"},
    ]
    base = {"name": "q", "scope": "all", "metric": "requests", "period": "day", "limit": "1"}
    for override in bad:
        with pytest.raises(SwitchyardError):
            mt(core, "quota_add", **{**base, **override})
    for action, args in [
        ("summary", {"days": 0}),
        ("usage", {"day": "today"}),
        ("quota_remove", {"name": "X Y"}),
    ]:
        with pytest.raises(SwitchyardError):
            mt(core, action, **args)
    assert core.run("module", "panel", {"id": "meter", "panel": "meter.status"}, actor="t")["prices"] == 2


def test_settings_and_optional_fs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes"))
    data = tmp_path / "data"
    data.mkdir()
    for bad in ("retention_days = 1", "nonsense = 1", 'models_dev_cache = "relative.json"'):
        (data / "config.toml").write_text(f"[modules.meter]\n{bad}\n", encoding="utf-8")
        c = Core(data_dir=data, hosting=True)
        try:
            c.run("module", "grant", {"id": "meter", "capability": "hermes.hooks"}, actor="t")
            c.run("module", "activate", {"id": "meter"}, actor="t")
            assert c.run("module", "show", {"id": "meter"}, actor="t")["status"] == "failed", bad
        finally:
            c.close()
    (data / "config.toml").write_text("", encoding="utf-8")
    c = Core(data_dir=data, hosting=True)
    try:
        for cap in ("hermes.hooks", "ui.panel"):  # fs.read is optional: auto-start does not wait for it
            c.run("module", "grant", {"id": "meter", "capability": cap}, actor="t")
        c.manager.start_auto(actor="t")
        assert c.run("module", "show", {"id": "meter"}, actor="t")["status"] == "active"
        assert c.run("module", "panel", {"id": "meter", "panel": "meter.status"}, actor="t")["prices"] == 0
        c.run("module", "grant", {"id": "meter", "capability": "fs.read"}, actor="t")
        assert c.run(
            "module", "action", {"id": "meter", "action": "prices_reload", "args": {}}, actor="t"
        ) == {"prices": 0}
    finally:
        c.close()


def test_router_cools_down_an_exhausted_quota_scope(core: Core, tmp_path: Path, clock: Clock) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "resources": [
                    {"id": f"{OR}/free/a:free", "provider": OR, "cost_class": "free"},
                    {"id": f"{OR}/free/b:free", "provider": OR, "cost_class": "free"},
                ]
            }
        ),
        encoding="utf-8",
    )
    for cap in ("fs.read", "ui.panel"):
        core.run("module", "grant", {"id": "resources", "capability": cap}, actor="t")
    core.run("module", "activate", {"id": "resources"}, actor="t")

    def res(action: str, **args: Any) -> Any:
        return core.run("module", "action", {"id": "resources", "action": action, "args": args}, actor="t")

    res("import_apply", import_id=res("import_file", path=str(catalog))["import_id"])
    res("pool_create", name="main", description="")
    for i, rid in enumerate((f"{OR}/free/a:free", f"{OR}/free/b:free")):
        res("set_state", id=rid, state="auto")
        res("pool_add", pool="main", id=rid, priority=i)
    res("bind", consumer="main", pool="main")
    for cap in ("hermes.hooks", "ui.panel", "llm.free"):
        core.run("module", "grant", {"id": "router", "capability": cap}, actor="t")
    core.run("module", "activate", {"id": "router"}, actor="t")
    core.manager._entry("router").instance.clock = clock

    def route() -> str:
        req = {"model": "x/default", "messages": [{"role": "user", "content": "hi"}]}
        out = core.bridge.dispatch_llm_request(req, {"provider": OR, "turn_id": "t", "api_request_id": "r"})
        return str((out or req)["model"])

    assert route() == "free/a:free"
    mt(
        core,
        "quota_add",
        name="a-day",
        scope=f"{OR}/free/a:free",
        metric="requests",
        period="day",
        limit="1",
        thresholds="100",
    )
    response(core, "free/a:free", usage())
    assert route() == "free/b:free"
    mt(
        core,
        "quota_add",
        name="or-day",
        scope=f"provider:{OR}",
        metric="requests",
        period="day",
        limit="1",
        thresholds="100",
    )
    response(core, "free/b:free", usage())
    assert route() == "x/default"  # whole provider exhausted: pass through, audited once
    assert route() == "x/default"
    passthrough = [r for r in core.run("audit", "tail", {"n": 200}, actor="t")
                   if r["action"] == "module.router.quota_passthrough"]  # fmt: skip
    assert len(passthrough) == 1
    configured_free = {"model": "free/a:free", "messages": [{"role": "user", "content": "hi"}]}
    out = core.bridge.dispatch_llm_request(
        configured_free, {"provider": OR, "turn_id": "t", "api_request_id": "r2"}
    )
    assert out is None  # configured model also inside the exhausted scope: nothing else to send, audited
    clock.now += 86_400
    assert route() == "free/a:free"  # cool-downs end with the quota period


def test_summary_totals_cover_every_row(core: Core) -> None:
    for i in range(205):
        response(core, f"m/{i}", usage(1, 1))
    s = mt(core, "summary", days=1)
    assert s["truncated"] is True and len(s["models"]) == 200
    assert s["totals"]["requests"] == 205 and s["totals"]["tokens"] == 410


def test_r1_quota_always_exhausts_and_cost_needs_prices(core: Core, tmp_path: Path) -> None:
    mt(
        core,
        "quota_add",
        name="warn",
        scope="all",
        metric="requests",
        period="day",
        limit="10",
        thresholds="80",
    )
    (q,) = [q for q in mt(core, "quotas")["quotas"] if q["name"] == "warn"]
    assert q["thresholds"] == [80, 100]  # 100 always fires meter.exhausted
    (tmp_path / "models_dev_cache.json").write_text("{}", encoding="utf-8")
    mt(core, "prices_reload")
    with pytest.raises(SwitchyardError, match="no model prices"):
        mt(core, "quota_add", name="usd", scope="all", metric="cost_usd", period="day", limit="1")
