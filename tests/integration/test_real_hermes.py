"""H1 D-4 / Question 9: Switchyard against a real Hermes Agent (pinned in CI, see ``hermes-integration`` in
``.github/workflows/ci.yml``). Skipped where Hermes is not installed.

Hermes discovers Switchyard through its ``hermes_agent.plugins`` entry point, loads it into a real
``PluginContext``, and these tests drive it only through Hermes's own dispatch functions.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

if os.environ.get("SWITCHYARD_REQUIRE_HERMES") == "1":  # the CI job that installs Hermes: never skip there
    import hermes_cli.plugins as plugins
else:
    plugins = pytest.importorskip("hermes_cli.plugins", reason="Hermes Agent is not installed")

pytestmark = pytest.mark.bundled_modules  # the real plugin, with the modules it ships


@pytest.fixture
def hermes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    home = tmp_path / "hermes-home"
    home.mkdir()
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - switchyard\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)
    plugins._reset_plugin_managers_for_tests()
    plugins.discover_plugins(force=True)
    yield plugins.get_plugin_manager()
    plugins._reset_plugin_managers_for_tests()
    import switchyard.hermes as adapter

    adapter.shutdown()


def _switchyard(manager: Any) -> dict[str, Any]:
    found = [p for p in manager.list_plugins() if p.get("name") == "switchyard"]
    assert found, manager.list_plugins()
    return found[0]


def test_hermes_loads_switchyard_through_its_entry_point(hermes: Any) -> None:
    info = _switchyard(hermes)
    assert info["enabled"] and info.get("error") in (None, "")
    assert info["tools"] == 3
    from tools.registry import registry

    for name in ("switchyard_modules", "switchyard_audit", "switchyard_host"):
        assert registry.get_entry(name) is not None, name


def test_model_tool_runs_through_the_hermes_registry(hermes: Any) -> None:
    from tools.registry import registry

    entry = registry.get_entry("switchyard_modules")
    raw = entry.handler({"action": "list"}, task_id="integration")
    result = json.loads(raw)
    assert result["ok"] is True
    rows = result["result"]
    if isinstance(rows, dict) and "untrusted_data" in rows:  # module text is labelled as data (R1)
        rows = rows["untrusted_data"]
    ids = {m["id"] for m in rows}
    assert {"router", "meter"} <= ids


def test_hooks_and_middleware_run_through_hermes_dispatch(hermes: Any) -> None:
    from hermes_cli.middleware import apply_llm_request_middleware

    assert plugins.has_hook("pre_llm_call") and plugins.has_middleware("llm_request")
    # no module is active: nothing blocks, and the request goes out unchanged
    blocks = plugins.invoke_hook("pre_llm_call", session_id="s", turn_id="t", user_message="hello")
    assert not [b for b in blocks if isinstance(b, dict) and b.get("action") == "block"]
    request = {"model": "vendor/model", "messages": [{"role": "user", "content": "hello"}]}
    out = apply_llm_request_middleware(request, provider="openrouter", api_request_id="r1", turn_id="t")
    assert out.payload["model"] == "vendor/model"
    usage = {"input_tokens": 1, "output_tokens": 1}
    plugins.invoke_hook("post_api_request", api_request_id="r1", provider="openrouter", model="vendor/model",
                        response_model="vendor/model", usage=usage)  # fmt: skip


def test_slash_command_runs_through_hermes(hermes: Any) -> None:
    assert "switchyard" in plugins.get_plugin_commands()
    handler = plugins.get_plugin_command_handler("switchyard")
    assert handler is not None
    out = handler("module list")
    assert "router" in str(out)


def test_h4_f8_gateway_ownership_check_is_the_one_hermes_ships(hermes: Any) -> None:
    """ADR-0014 relies on ``gateway.status.owns_gateway_runtime_lock``: it must exist in the pinned Hermes, be
    in the published plugin API, and say that this test process is not the gateway runtime."""
    import importlib
    import sys

    import hermes_cli

    import switchyard.hermes as adapter

    status = importlib.import_module("gateway.status")
    assert callable(status.owns_gateway_runtime_lock)
    assert sys.modules["gateway.status"] is status
    assert adapter._gateway_runtime() is False
    api = json.loads(
        (Path(hermes_cli.__file__).resolve().parent / "data" / "plugin_api.json").read_text(encoding="utf-8")
    )
    assert '"gateway.status"' in json.dumps(api)
    # a plugin load in a process that is not the gateway does not host; its first turn does
    current = adapter.current()
    assert not current.core.hosting
    plugins.invoke_hook("pre_llm_call", session_id="s", turn_id="t", user_message="hello")
    assert current.core.hosting


def test_dashboard_api_imports_against_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("switchyard_dashboard_api", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.router.routes


def test_hermes_installs_nothing_for_the_plugin() -> None:
    """1.1 S-1: Hermes's own reader sees no packages to put into its shared environment (a sealed desktop
    install reports 'install out of sync' when a plugin's package lands there)."""
    declarations = pytest.importorskip("pm.plugin_declarations")
    declaration = declarations.read_python_declaration(Path(__file__).resolve().parents[2])
    assert declaration.external and not declaration.installs_packages
