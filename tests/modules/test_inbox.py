"""M9: notify capability, inbox module, reports, dashboard tab (static checks) and its backend proxy."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hermes_signalbox.contract import run_contract
from hermes_signalbox.core import BUILTIN_MODULES, Core
from hermes_signalbox.errors import SignalboxError

pytestmark = pytest.mark.bundled_modules
ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = Path(BUILTIN_MODULES) / "inbox"


def ib(core: Core, action: str, actor: str = "t", **args: Any) -> Any:
    return core.run("module", "action", {"id": "inbox", "action": action, "args": args}, actor=actor)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes"))


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    c = Core(data_dir=tmp_path / "data", hosting=True)
    for cap in ("core.read", "ui.panel"):
        c.run("module", "grant", {"id": "inbox", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "inbox"}, actor="t")
    yield c
    c.close()


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_notify_reaches_the_inbox_redacted_and_bounded(core: Core) -> None:
    from hermes_signalbox.notify import NotifyBroker

    notify = NotifyBroker(core.bus.publish, core.audit, core.redactor.redact).for_module("tester")
    secret = "sk-or-v1-" + "a" * 64
    notify.send("high", "Disk\nfull " + "x" * 300, f"key {secret}")
    item = ib(core, "list")["items"][0]
    assert item["severity"] == "high" and item["module"] == "tester" and len(item["title"]) == 120
    assert "\n" not in item["title"] and secret not in item["detail"]
    with pytest.raises(SignalboxError):
        notify.send("urgent", "x")
    with pytest.raises(SignalboxError):
        notify.send("info", "  ")
    with pytest.raises(SignalboxError, match="notify"):
        _ = core.manager._entry("inbox").instance.ctx.notify  # not granted
    assert "module.notify" in [r["action"] for r in core.run("audit", "tail", {"n": 20}, actor="t")]


def test_alert_events_min_severity_ack_and_bounds(core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    core.bus.publish("meter", "meter.exhausted", {"quota": "day", "scope": "all"})
    core.bus.publish("workers", "workers.loop", {"role": "coder", "goal_sha": "ab"})
    core.bus.publish("supervisor", "supervisor.alert", {"key": "audit:chain", "severity": "critical"})
    items = ib(core, "list")["items"]
    assert {i["type"] for i in items} == {"meter.exhausted", "workers.loop", "supervisor.alert"}
    assert next(i for i in items if i["type"] == "supervisor.alert")["severity"] == "critical"
    ib(core, "ack", id=items[0]["id"])
    assert len(ib(core, "list", state="acked")["items"]) == 1
    assert ib(core, "ack_all")["acked"] == 2 and ib(core, "list")["items"] == []
    with pytest.raises(SignalboxError, match="no such"):
        ib(core, "ack", id="nope")
    with pytest.raises(SignalboxError, match="read-only"):
        ib(core, "list", actor="hermes")  # module-written text is for the operator, not the model
    for bad in ({"state": "x"}, {"limit": 0}):
        with pytest.raises(SignalboxError):
            ib(core, "list", **bad)
    monkeypatch.setattr("hermes_signalbox.modules.inbox.inbox_module.KEEP", 5, raising=False)
    inst = core.manager._entry("inbox").instance
    inst.on_event.__globals__["KEEP"] = 5
    for i in range(12):
        core.bus.publish("meter", "meter.threshold", {"quota": f"q{i}"})
    assert len(ib(core, "list", state="all", limit=500)["items"]) == 5
    assert core.run("module", "panel", {"id": "inbox", "panel": "inbox.status"}, actor="t")["open"]


def test_failed_modules_and_min_severity(tmp_path: Path) -> None:
    data = tmp_path / "d"
    data.mkdir()
    (data / "config.toml").write_text(
        "[modules.inbox]\nmin_severity = 'high'\n[modules.supervisor]\ninterval_seconds = 1\n",
        encoding="utf-8",
    )
    c = Core(data_dir=data, hosting=True)
    try:
        for cap in ("core.read", "ui.panel"):
            c.run("module", "grant", {"id": "inbox", "capability": cap}, actor="t")
        c.run("module", "activate", {"id": "inbox"}, actor="t")
        for cap in ("schedule", "core.read", "ui.panel"):
            c.run("module", "grant", {"id": "supervisor", "capability": cap}, actor="t")
        c.run("module", "activate", {"id": "supervisor"}, actor="t")  # bad setting: fails
        c.bus.publish("workers", "workers.loop", {"role": "x"})  # low: dropped
        items = ib(c, "list")["items"]
        assert [i["type"] for i in items] == ["module.failed"] and items[0]["module"] == "supervisor"
    finally:
        c.close()
    (data / "config.toml").write_text("[modules.inbox]\nmin_severity = 'loud'\n", encoding="utf-8")
    c = Core(data_dir=data, hosting=True)
    try:
        c.run("module", "activate", {"id": "inbox"}, actor="t")
        assert c.run("module", "show", {"id": "inbox"}, actor="t")["status"] == "failed"
    finally:
        c.close()


def test_reports(core: Core) -> None:
    health = core.run("report", "show", {"kind": "health"}, actor="t")
    assert any(m["id"] == "inbox" for m in health["modules"]) and health["failed"] == []
    usage = core.run("report", "show", {"kind": "usage"}, actor="hermes")
    assert usage["meter"] == {"unavailable": "not active"}  # H4 R1-F12: a reason, not a class name
    security = core.run("report", "show", {"kind": "security"}, actor="t")
    assert security["audit"]["ok"] is True
    core.run("module", "grant", {"id": "meter", "capability": "ui.panel"}, actor="t")
    changes = core.run("report", "show", {"kind": "changes"}, actor="t")["changes"]
    assert any(r["action"] == "policy.granted" for r in changes)
    with pytest.raises(SignalboxError):
        core.run("report", "show", {"kind": "secrets"}, actor="t")


def test_dashboard_bundle_is_accessible_and_local() -> None:
    manifest = json.loads((ROOT / "dashboard" / "manifest.json").read_text("utf-8"))
    assert manifest["name"] == "signalbox" and manifest["api"] == "plugin_api.py"
    js = (
        (ROOT / manifest["entry"].join(["dashboard/", ""])).read_text("utf-8")
        if False
        else (ROOT / "dashboard" / manifest["entry"]).read_text("utf-8")
    )
    assert re.findall(r"https?://", js) == []  # no outbound telemetry or third-party hosts
    assert "fetch(" not in js.replace("SDK.fetchJSON(", "")  # only the SDK's authenticated fetch
    assert "dangerouslySetInnerHTML" not in js and "innerHTML" not in js and "eval(" not in js
    assert 'h("div", { onClick' not in js and "onClick" in js  # clickable things are buttons
    for needle in (
        'role: "tablist"',
        'role: "tab"',
        '"aria-selected"',
        '"aria-live": "polite"',
        'scope: "col"',
        'h("caption"',
        'type: "button"',
        'h("label"',
    ):
        assert needle in js, needle
    assert ":focus-visible" in (ROOT / "dashboard" / "dist" / "style.css").read_text("utf-8")


def test_dashboard_backend_proxy(core: Core, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str = "") -> None:
            super().__init__(detail)
            self.status_code = status_code

    class Router:
        def __init__(self) -> None:
            self.routes: dict[tuple[str, str], Any] = {}

        def _add(self, method: str, path: str) -> Any:
            def deco(fn: Any) -> Any:
                self.routes[(method, path)] = fn
                return fn

            return deco

        def get(self, path: str) -> Any:
            return self._add("GET", path)

        def post(self, path: str, dependencies: Any = None) -> Any:
            return self._add("POST", path)

    fake = types.ModuleType("fastapi")
    fake.APIRouter = Router  # type: ignore[attr-defined]
    fake.HTTPException = HTTPException  # type: ignore[attr-defined]
    fake.Depends = lambda fn: fn  # type: ignore[attr-defined]
    fake.Request = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastapi", fake)
    spec = importlib.util.spec_from_file_location("sy_dashboard_api", ROOT / "dashboard" / "plugin_api.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("SIGNALBOX_DATA_DIR", str(tmp_path / "nothing"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.modules())
    assert exc.value.status_code == 503
    calls: list[tuple[str, str, dict[str, Any]]] = []

    class Client:
        def request(self, noun: str, verb: str, params: dict[str, Any]) -> Any:
            calls.append((noun, verb, params))
            return core.run(noun, verb, params, actor="api")

    monkeypatch.setattr("hermes_signalbox.api.ApiClient.from_data_dir", lambda d: Client())
    assert any(m["id"] == "inbox" for m in asyncio.run(mod.modules()))
    assert asyncio.run(mod.report("health"))["kind"] == "health"
    # H5 WP4 (#208): the route adds the grouped view and the open count to the stored items
    assert asyncio.run(mod.inbox("open")) == {"items": [], "groups": [], "open": 0}
    asyncio.run(mod.module_lifecycle("inbox", "deactivate"))
    for call in (
        mod.module_lifecycle("inbox", "remove"),
        mod.report("secrets"),
        mod.panel("Bad!", "x"),
        mod.inbox_ack("../../x"),
        mod.inbox("weird"),
        mod.module_show("../etc"),
    ):
        with pytest.raises(HTTPException):
            asyncio.run(call)
    # H4 R1-F11: the module list also asks each running module's health (in DASHBOARD_OPS since M9)
    assert {c[1] for c in calls} <= {"list", "show", "panel", "activate", "deactivate", "action", "health"}


def test_dashboard_api_profile_refuses_privileged_ops(core: Core) -> None:
    from hermes_signalbox.api import ApiClient, ControlServer

    server = ControlServer(core, profile="dashboard")
    server.start()
    try:
        client = ApiClient.from_data_dir(core.data_dir)
        assert any(m["id"] == "inbox" for m in client.request("module", "list", {}))
        for noun, verb, params in [
            ("module", "grant", {"id": "inbox", "capability": "ui.panel"}),
            ("module", "revoke", {"id": "inbox", "capability": "ui.panel"}),
            ("module", "remove", {"id": "inbox"}),
        ]:
            with pytest.raises(SignalboxError, match="not served by the Signalbox API inside Hermes"):
                client.request(noun, verb, params)
        # H5 WP3 (#206): the start mode is served by the dashboard profile, audited as the dashboard
        assert client.request("module", "mode", {"id": "inbox", "mode": "manual"}) == {"mode": "manual"}
        assert core.audit_log.tail(1)[0]["actor"] == "api"
        core.bus.publish("meter", "meter.exhausted", {"quota": "day"})
        items = client.request("module", "action", {"id": "inbox", "action": "list", "args": {}})["items"]
        client.request("module", "action", {"id": "inbox", "action": "ack", "args": {"id": items[0]["id"]}})
        for cap in ("hermes.output", "ui.panel"):
            core.run("module", "grant", {"id": "trimmer", "capability": cap}, actor="t")
        core.run("module", "activate", {"id": "trimmer"}, actor="t")
        with pytest.raises(SignalboxError, match="read-only"):  # other module actions: model rights only
            client.request("module", "action", {"id": "trimmer", "action": "preview", "args": {"text": "x"}})
        assert (
            client.request("module", "action", {"id": "trimmer", "action": "report", "args": {}})["tools"]
            == []
        )
    finally:
        server.shutdown()
    with pytest.raises(SignalboxError):
        ControlServer(core, profile="root")


def test_review_fixes(core: Core) -> None:
    from hermes_signalbox.manifest import validate_document
    from hermes_signalbox.notify import NotifyBroker

    secret = "TOPSECRETVALUE12345"  # noqa: S105 - test value
    broker = NotifyBroker(core.bus.publish, core.audit, lambda s: s.replace(secret, "[redacted]"))
    out = broker.send("tester", "info", "x" * 112 + secret)
    assert "TOPSECRE" not in out["title"]
    core.bus.publish(
        "evil", "core.notify", {"title": "fake", "severity": "critical"}
    )  # wrong source: ignored
    assert all(i["title"] != "fake" for i in ib(core, "list", state="all")["items"])
    doc = {"schema": 1, "module": {"id": "core"}}
    assert any("reserved" in e for e in validate_document(doc))
    inst = core.manager._entry("inbox").instance
    inst.on_event.__globals__["KEEP"] = 5
    core.bus.publish("supervisor", "supervisor.alert", {"key": "audit:chain", "severity": "critical"})
    for i in range(20):
        core.bus.publish("workers", "workers.loop", {"role": f"r{i}"})
    kept = ib(core, "list", state="all", limit=500)["items"]
    assert len(kept) == 5 and any(i["severity"] == "critical" for i in kept)
    inst.on_event.__globals__["KEEP"] = 1000


def test_h5_r10_a_notice_is_from_whoever_published_it(core: Core) -> None:
    """Independent review R-10: only the core may say which module an event is about."""
    core.bus.publish("evil", "evil.alert", {"module": "supervisor", "severity": "critical"})
    core.bus.publish("core", "module.failed", {"module": "router", "error": "x"})
    by_type = {i["type"]: i for i in ib(core, "list", state="all")["items"]}
    assert by_type["module.failed"]["module"] == "router"
    if "evil.alert" in by_type:  # shown only if the inbox takes that event type at all
        assert by_type["evil.alert"]["module"] == "evil"
    inst = core.manager._entry("inbox").instance
    inst.on_event(types.SimpleNamespace(type="module.failed", source="evil", data={"module": "supervisor"}))
    newest = ib(core, "list", state="all")["items"]
    assert "supervisor" not in {i["module"] for i in newest}
    assert "evil" in {i["module"] for i in newest}
