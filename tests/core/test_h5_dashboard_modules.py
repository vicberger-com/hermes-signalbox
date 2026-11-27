"""H5 WP3 (#206, #208): the dashboard backend serves the label glossary and can set a module's start mode.

The backend runs inside Hermes's web server, so FastAPI is replaced by a recording stand-in here; the
real-FastAPI check is in ``tests/integration``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sy_testing import write_module

from hermes_signalbox import labels
from hermes_signalbox.api import DASHBOARD_OPS, ControlServer
from hermes_signalbox.core import Core

ROOT = Path(__file__).resolve().parents[2]


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _Router:
    def __init__(self) -> None:
        self.order: list[tuple[str, str]] = []
        self.guards: dict[tuple[str, str], Any] = {}

    def _add(self, method: str, path: str, dependencies: Any) -> Any:
        def deco(fn: Any) -> Any:
            self.order.append((method, path))
            self.guards[(method, path)] = dependencies
            return fn

        return deco

    def get(self, path: str) -> Any:
        return self._add("GET", path, None)

    def post(self, path: str, dependencies: Any = None) -> Any:
        return self._add("POST", path, dependencies)


class _Request:
    def __init__(self, body: Any = None, site: str | None = None) -> None:
        self._body = body
        self.sent: dict[str, str] = {}
        self.headers = types.SimpleNamespace(
            getlist=lambda name: [site] if site else [],
            get=lambda name, default=None: self.sent.get(name, default),
        )

    async def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    data = tmp_path / "data"
    write_module(data / "modules", "aaa", isolation="subprocess", request=("schedule",))
    with Core(data_dir=data, hosting=True) as c:
        yield c


@pytest.fixture
def server(core: Core) -> Iterator[ControlServer]:
    """The restricted API profile Hermes runs for the dashboard. Never started: only its rules are used."""
    made = ControlServer(core, port=0, profile="dashboard")
    yield made
    made._httpd.server_close()


@pytest.fixture
def api(core: Core, server: ControlServer, monkeypatch: pytest.MonkeyPatch) -> Any:
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = _Router  # type: ignore[attr-defined]
    fastapi.HTTPException = HTTPException  # type: ignore[attr-defined]
    fastapi.Depends = lambda fn: fn  # type: ignore[attr-defined]
    fastapi.Request = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    monkeypatch.setenv("SIGNALBOX_DATA_DIR", str(core.data_dir))

    class Client:
        def request(self, noun: str, verb: str, params: dict[str, Any]) -> Any:
            actor = server.actor_for(noun, verb, params)  # the restricted profile decides, as in Hermes
            assert actor is not None, f"the dashboard profile does not serve '{noun} {verb}'"
            return core.run(noun, verb, params, actor=actor)

    monkeypatch.setattr("hermes_signalbox.api.ApiClient.from_data_dir", lambda d: Client())
    spec = importlib.util.spec_from_file_location("sy_dashboard_h5", ROOT / "dashboard" / "plugin_api.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_h5_wp3_labels_route_serves_the_glossary_without_calling_the_core(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_call(data_dir: Path) -> Any:
        raise AssertionError("the labels are static: no core call")

    monkeypatch.setattr("hermes_signalbox.api.ApiClient.from_data_dir", no_call)
    assert asyncio.run(api.glossary()) == labels.glossary()
    assert ("GET", "/labels") in api.router.order


def test_h5_wp3_mode_is_set_from_the_dashboard_and_audited_as_the_dashboard(api: Any, core: Core) -> None:
    reply = asyncio.run(api.module_mode("aaa", _Request({"mode": "disabled"})))
    assert reply == {"mode": "disabled"}
    assert core.manager.info("aaa").mode == "disabled"
    last = core.audit_log.tail(1)[0]
    assert (last["action"], last["actor"], last["module"]) == ("module.mode_changed", "api", "aaa")
    assert last["detail"]["mode"] == "disabled"


def test_h5_wp3_mode_route_sits_behind_the_write_guard_and_before_the_generic_route(api: Any) -> None:
    route = ("POST", "/modules/{module_id}/mode")
    assert api.router.guards[route] == [api._own_page_only]
    # declared first, or "/modules/{module_id}/{verb}" would answer it with "unknown action"
    assert api.router.order.index(route) < api.router.order.index(("POST", "/modules/{module_id}/{verb}"))
    for site in ("cross-site", "same-site"):
        with pytest.raises(HTTPException) as refused:
            api._own_page_only(_Request(site=site))
        assert refused.value.status_code == 403
    api._own_page_only(_Request(site="same-origin"))  # the dashboard's own page passes


@pytest.mark.parametrize(
    ("module_id", "body"),
    [
        ("aaa", {"mode": "always"}),
        ("aaa", {"mode": 3}),
        ("aaa", {}),
        ("aaa", ["auto"]),
        ("aaa", ValueError("not JSON")),
        ("../x", {"mode": "auto"}),
    ],
)
def test_h5_wp3_a_bad_mode_request_is_refused_and_changes_nothing(
    api: Any, core: Core, module_id: str, body: Any
) -> None:
    before = (core.manager.info("aaa").mode, len(core.audit_log.tail(500)))
    with pytest.raises(HTTPException) as refused:
        asyncio.run(api.module_mode(module_id, _Request(body)))
    assert refused.value.status_code == 400
    assert (core.manager.info("aaa").mode, len(core.audit_log.tail(500))) == before


def test_h5_wp3_the_dashboard_profile_serves_mode_but_still_not_grants_or_removal(
    server: ControlServer,
) -> None:
    assert server.actor_for("module", "mode", {"id": "aaa", "mode": "manual"}) == "api"
    for verb in ("grant", "revoke", "remove", "update", "rollback", "reload"):
        assert ("module", verb) not in DASHBOARD_OPS
        assert server.actor_for("module", verb, {"id": "aaa"}) is None


def test_h5_wp3_auto_mode_from_the_dashboard_does_not_start_a_module_without_its_grants(
    api: Any, core: Core
) -> None:
    asyncio.run(api.module_mode("aaa", _Request({"mode": "auto"})))
    core.manager.start_auto(actor="core")
    assert core.manager.info("aaa").status.value == "verified"  # "schedule" is not granted


def test_h5_wp4_the_report_route_adds_what_the_page_lays_out(api: Any, core: Core) -> None:
    shown = asyncio.run(api.report("health"))
    assert shown["kind"] == "health" and shown["summary"]["headline"].startswith("0 of 1 modules running")
    assert shown["view"]["rows"] == [
        {
            "id": "aaa",
            "state": "Ready, needs permissions",
            "detail": "",
            "needs": ["Run on a timer (schedule)"],
        }
    ]
    changes = asyncio.run(api.report("changes"))
    assert changes["view"] == {"rows": []} and "changes" in changes  # the raw records are still there


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"content-length": str(64 * 1024 + 1)}, 413),
        ({"content-length": "many"}, 400),
        ({"content-type": "text/plain"}, 415),
        ({"content-type": "application/json; charset=utf-8", "content-length": "17"}, None),
    ],
)
def test_h5_r11_the_mode_route_refuses_an_oversized_or_non_json_body_before_reading_it(
    api: Any, core: Core, headers: dict[str, str], status: int | None
) -> None:
    request = _Request({"mode": "disabled"})
    request.sent = headers
    if status is None:
        assert asyncio.run(api.module_mode("aaa", request)) == {"mode": "disabled"}
        return
    with pytest.raises(HTTPException) as refused:
        asyncio.run(api.module_mode("aaa", request))
    assert refused.value.status_code == status
    assert core.manager.info("aaa").mode != "disabled"
