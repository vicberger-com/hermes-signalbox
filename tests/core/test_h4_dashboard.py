"""H4 R1-F10, R1-F11: the dashboard backend finds the data directory the plugin uses, creates nothing, and
fills the Health column.

The stand-ins below copy what Hermes v0.23.3 does (``hermes_cli/plugins_state.py``,
``hermes_cli/plugins_manifest.py``, ``plugins/plugin_storage.py``): the agent plugin's ``ctx.state.data_dir``
is ``<home>/plugin-data/agent-plugin-<slug>-<sha256[:8]>``, while ``plugin_data_dir(name)`` is
``<home>/plugin-data/<name>`` and creates it. The real-Hermes check is in ``tests/integration``.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sy_testing import FakeHermesCtx, write_module

from switchyard import hermes as adapter_mod
from switchyard.core import Core
from switchyard.hermes import HermesAdapter

ROOT = Path(__file__).resolve().parents[2]


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _Router:
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


def _hermes_namespace(key: str) -> str:
    """``hermes_cli.plugins_manifest._portable_data_namespace`` (v0.23.3)."""
    slug = "".join(ch if ch.isascii() and (ch.isalnum() or ch in "_-") else "-" for ch in key.lower())
    return f"agent-plugin-{slug.strip('-_') or 'plugin'}-{hashlib.sha256(key.encode()).hexdigest()[:8]}"


class Hermes:
    """The Hermes names the dashboard backend may use, on a temporary Hermes home."""

    def __init__(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.home = home
        self.config: dict[str, Any] = {}
        hermes = self

        class PluginState:
            def __init__(self, plugin_id: str, data_namespace: str = "") -> None:
                self._ns = data_namespace or _hermes_namespace(plugin_id)

            @property
            def data_dir(self) -> Path:
                return hermes.home / "plugin-data" / self._ns

        def plugin_data_dir(name: str) -> Path:
            root = hermes.home / "plugin-data" / name
            root.mkdir(parents=True, exist_ok=True)
            return root

        self.PluginState = PluginState
        fastapi = types.ModuleType("fastapi")
        fastapi.APIRouter = _Router  # type: ignore[attr-defined]
        fastapi.HTTPException = HTTPException  # type: ignore[attr-defined]
        fastapi.Depends = lambda fn: fn  # type: ignore[attr-defined]
        fastapi.Request = object  # type: ignore[attr-defined]
        state_mod = types.ModuleType("hermes_cli.plugins_state")
        state_mod.PluginState = PluginState  # type: ignore[attr-defined]
        config_mod = types.ModuleType("hermes_cli.config")
        config_mod.load_config_readonly = lambda: hermes.config  # type: ignore[attr-defined]
        config_mod.load_config = lambda: hermes.config  # type: ignore[attr-defined]
        storage = types.ModuleType("plugins.plugin_storage")
        storage.plugin_data_dir = plugin_data_dir  # type: ignore[attr-defined]
        for name, mod in {
            "fastapi": fastapi,
            "hermes_cli": types.ModuleType("hermes_cli"),
            "hermes_cli.plugins_state": state_mod,
            "hermes_cli.config": config_mod,
            "plugins": types.ModuleType("plugins"),
            "plugins.plugin_storage": storage,
        }.items():
            monkeypatch.setitem(sys.modules, name, mod)

    def plugin_dir(self) -> Path:
        """``ctx.state.data_dir`` of the agent plugin."""
        return Path(self.PluginState("switchyard").data_dir)

    def listing(self) -> list[str]:
        root = self.home / "plugin-data"
        return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


@pytest.fixture
def hermes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Hermes:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)
    home = tmp_path / "hermes-home"
    home.mkdir()
    return Hermes(home, monkeypatch)


@pytest.fixture
def api(hermes: Hermes) -> Any:
    spec = importlib.util.spec_from_file_location("sy_dashboard_h4", ROOT / "dashboard" / "plugin_api.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def adapters() -> Iterator[Callable[[Path, dict[str, Any] | None], HermesAdapter]]:
    made: list[HermesAdapter] = []

    def make(state_dir: Path, settings: dict[str, Any] | None = None) -> HermesAdapter:
        adapter = HermesAdapter(FakeHermesCtx(state_dir, settings))
        made.append(adapter)
        return adapter

    yield make
    for adapter in reversed(made):
        adapter.close()


# T9: the same directory as the agent plugin ---------------------------------------------------------------


def test_h4_r1_f10_dashboard_resolves_the_agent_plugins_data_dir(
    hermes: Hermes, api: Any, adapters: Callable[..., HermesAdapter]
) -> None:
    adapter = adapters(hermes.plugin_dir())
    assert adapter.core.data_dir.name.startswith("agent-plugin-switchyard-")
    assert api._data_dir() == adapter.core.data_dir


def test_h4_r1_f10_dashboard_follows_the_plugins_data_dir_setting(
    hermes: Hermes, api: Any, adapters: Callable[..., HermesAdapter], tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    hermes.config = {"plugins": {"entries": {"switchyard": {"settings": {"data_dir": str(elsewhere)}}}}}
    adapter = adapters(hermes.plugin_dir(), {"data_dir": str(elsewhere)})
    assert adapter.core.data_dir == elsewhere
    assert api._data_dir() == elsewhere


def test_h4_r1_f10_the_setting_beats_the_environment_variable_as_in_the_plugin(
    hermes: Hermes, api: Any, adapters: Callable[..., HermesAdapter], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.setenv("SWITCHYARD_DATA_DIR", str(tmp_path / "from-env"))
    chosen = tmp_path / "from-setting"
    hermes.config = {"plugins": {"entries": {"switchyard": {"settings": {"data_dir": str(chosen)}}}}}
    adapter = adapters(hermes.plugin_dir(), {"data_dir": str(chosen)})
    assert adapter.core.data_dir == chosen == api._data_dir()


def test_h4_r1_f10_the_environment_variable_still_wins_over_the_plugin_dir(
    hermes: Hermes, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SWITCHYARD_DATA_DIR", str(tmp_path / "from-env"))
    assert api._data_dir() == tmp_path / "from-env"


# T10: reading creates nothing -----------------------------------------------------------------------------


def test_h4_r1_f10_a_read_with_the_api_off_creates_no_directory(hermes: Hermes, api: Any) -> None:
    before = hermes.listing()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.modules())
    assert exc.value.status_code == 503
    assert hermes.listing() == before


def test_h4_r1_f10_the_api_is_found_where_the_plugin_serves_it(
    hermes: Hermes, api: Any, adapters: Callable[..., HermesAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The R1-F10 symptom: the tab said "API is off" while the plugin served it from its own directory."""
    data = hermes.plugin_dir()
    write_module(data / "modules", "m1", isolation="subprocess", activation="manual")
    (data / "config.toml").write_text("[api]\nenabled = true\nport = 0\n", encoding="utf-8")
    monkeypatch.setattr(adapter_mod, "_gateway_runtime", lambda: True)
    adapter = adapters(data)
    adapter.register()
    assert adapter.core.hosting
    before = hermes.listing()
    rows = asyncio.run(api.modules())
    assert [r["id"] for r in rows] == ["m1"]
    assert hermes.listing() == before


# T11: the Health column -----------------------------------------------------------------------------------


@pytest.fixture
def routed(hermes: Hermes, api: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Core]:
    data = tmp_path / "data"
    write_module(data / "modules", "aaa", isolation="subprocess")
    write_module(data / "modules", "bbb", isolation="subprocess")
    core = Core(data_dir=data, hosting=True)

    class Client:
        def request(self, noun: str, verb: str, params: dict[str, Any]) -> Any:
            return core.run(noun, verb, params, actor="api")

    monkeypatch.setattr("switchyard.api.ApiClient.from_data_dir", lambda d: Client())
    yield core
    core.close()


def test_h4_r1_f11_list_rows_carry_health(api: Any, routed: Core) -> None:
    routed.run("module", "activate", {"id": "aaa"}, actor="cli")
    rows = {r["id"]: r for r in asyncio.run(api.modules())}
    assert rows["aaa"]["health"] == "ok"
    assert rows["bbb"]["health"] == ""  # not running: no check to run


def test_h4_r1_f11_a_failing_check_says_so(api: Any, routed: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    routed.run("module", "activate", {"id": "aaa"}, actor="cli")
    monkeypatch.setattr(routed.manager, "health", lambda module_id: (False, "disk full " + "x" * 300))
    [row] = [r for r in asyncio.run(api.modules()) if r["id"] == "aaa"]
    assert row["health"].startswith("failing: disk full") and len(row["health"]) <= 120


def test_h4_r1_f11_a_health_call_that_errors_leaves_the_list_intact(
    api: Any, routed: Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    from switchyard.errors import SwitchyardError

    routed.run("module", "activate", {"id": "aaa"}, actor="cli")

    def boom(module_id: str) -> tuple[bool, str]:
        raise SwitchyardError("gone")

    monkeypatch.setattr(routed.manager, "health", boom)
    rows = {r["id"]: r for r in asyncio.run(api.modules())}
    assert rows["aaa"]["health"] == "unknown" and rows["aaa"]["status"] == "active"
