"""Hermes plugin adapter, tested against a recording stand-in for Hermes's PluginContext."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sy_testing import write_module

from switchyard import hermes as adapter_mod
from switchyard.hermes import MODEL_TOOL_ACTIONS, HermesAdapter, register


class FakeCtx:
    def __init__(self, data_dir: Path, settings: dict[str, Any] | None = None) -> None:
        self.state = SimpleNamespace(data_dir=data_dir)
        self.settings = settings or {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.commands: dict[str, Callable[[str], str | None]] = {}
        self.cli: dict[str, dict[str, Any]] = {}
        self.idle: dict[str, dict[str, Any]] = {}
        self.patterns: list[str] = []
        self.hooks: dict[str, Callable[..., Any]] = {}
        self.middleware: dict[str, Callable[..., Any]] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def register_tool(self, name: str, toolset: str, schema: dict[str, Any], handler: Callable[..., str],
                      **kw: Any) -> None:  # fmt: skip
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kw}

    def register_command(self, name: str, handler: Callable[[str], str | None], description: str = "",
                         args_hint: str = "") -> None:  # fmt: skip
        self.commands[name] = handler

    def register_cli_command(
        self,
        name: str,
        help: str,
        setup_fn: Callable[..., None],
        handler_fn: Any = None,
        description: str = "",
    ) -> None:
        self.cli[name] = {"setup": setup_fn, "handler": handler_fn}

    def register_idle_task(self, name: str, fn: Callable[[Any], str | None], *, interval_hours: float,
                           min_idle_hours: float = 2.0, first_run: str = "defer") -> None:  # fmt: skip
        self.idle[name] = {"fn": fn, "interval_hours": interval_hours}

    def register_redaction_patterns(self, patterns: list[str]) -> int:
        self.patterns.extend(patterns)
        return len(patterns)

    def register_hook(self, name: str, fn: Callable[..., Any]) -> None:
        self.hooks[name] = fn

    def register_middleware(self, kind: str, fn: Callable[..., Any]) -> None:
        self.middleware[kind] = fn


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)
    monkeypatch.setattr(adapter_mod, "TICK_SECONDS", 0.05)


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[FakeCtx]:
    data = tmp_path / "plugin-data"
    write_module(data / "modules", "ext", isolation="subprocess", request=("schedule",))
    fake = FakeCtx(data)
    yield fake
    adapter_mod.shutdown()


def _tool(ctx: FakeCtx, name: str, **args: Any) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(ctx.tools[name]["handler"](args, task_id="t1"))
    return result


def test_register_contributes_tools_commands_cli_idle_task_and_patterns(ctx: FakeCtx) -> None:
    register(ctx)
    assert set(ctx.tools) == {"switchyard_modules", "switchyard_audit", "switchyard_host"}
    assert all(t["toolset"] == "switchyard" for t in ctx.tools.values())
    for name, tool in ctx.tools.items():
        schema = tool["schema"]
        assert schema["name"] == name and schema["description"] and schema["parameters"]["type"] == "object"
    assert set(ctx.commands) == {"switchyard"} and set(ctx.cli) == {"switchyard"}
    assert ctx.idle["switchyard-audit-verify"]["interval_hours"] == 24
    assert ctx.patterns and all(p[:2].isalnum() or p[:2].replace("_", "a").isalnum() for p in ctx.patterns)


def test_plugin_yaml_declares_what_register_provides(ctx: FakeCtx) -> None:
    register(ctx)
    text = (Path(__file__).resolve().parents[2] / "plugin.yaml").read_text(encoding="utf-8")
    for tool in ctx.tools:
        assert f"  - {tool}" in text
    assert "manifest_version: 2" in text


def test_model_tools_list_and_run_modules(ctx: FakeCtx) -> None:
    register(ctx)
    listed = _tool(ctx, "switchyard_modules", action="list")
    assert listed["ok"] and listed["result"][0]["id"] == "ext"
    assert _tool(ctx, "switchyard_modules", action="activate", id="ext")["result"]["status"] == "active"
    assert _tool(ctx, "switchyard_modules", action="health", id="ext")["result"] == {
        "ok": True,
        "detail": "ok",
    }
    assert _tool(ctx, "switchyard_modules", action="deactivate", id="ext")["ok"]
    actors = {r["actor"] for r in _tool(ctx, "switchyard_audit", action="tail", n=10)["result"]}
    assert "hermes" in actors
    assert _tool(ctx, "switchyard_audit", action="verify")["result"]["ok"] is True
    assert _tool(ctx, "switchyard_host")["result"]["profile_name"]


@pytest.mark.parametrize("action", ["grant", "revoke", "mode", "remove"])
def test_model_tools_cannot_change_grants_or_modes(ctx: FakeCtx, action: str) -> None:
    register(ctx)
    out = _tool(ctx, "switchyard_modules", action=action, id="ext", capability="schedule", mode="auto")
    assert out["ok"] is False and out["error"] == "UsageError"
    assert action not in MODEL_TOOL_ACTIONS


def test_tool_errors_are_json_and_carry_no_foreign_messages(
    ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(ctx)
    out = _tool(ctx, "switchyard_modules", action="activate", id="ghost")
    assert out == {"ok": False, "error": "SwitchyardError", "message": "unknown module 'ghost'"}
    assert _tool(ctx, "switchyard_modules")["error"] == "UsageError"  # no action
    assert _tool(ctx, "switchyard_modules", action="list", id=7)["error"] == "UsageError"

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("token=sk-should-not-leak")

    monkeypatch.setattr(adapter_mod.current().core, "run", boom)
    out = _tool(ctx, "switchyard_modules", action="list")
    assert out == {"ok": False, "error": "RuntimeError", "message": ""}


def test_slash_command_is_the_human_path_for_grants(ctx: FakeCtx) -> None:
    register(ctx)
    handler = ctx.commands["switchyard"]
    assert "module grant" in (handler("") or "")  # help text lists operations
    assert "granted" in (handler("module grant ext capability=schedule") or "")
    assert "schedule" in (handler("module show ext") or "")
    assert "error" in (handler("module grant ext capability=net.outbound") or "")
    assert "error" in (handler("module launch") or "")
    assert "error" in (handler("module grant ext capability") or "")  # malformed key=value
    assert '"removed": "ext"' in (handler("module remove ext keep_data=true") or "")
    assert handler("module list") == "[]"


def test_cli_command_delegates_to_the_switchyard_cli(
    ctx: FakeCtx, capsys: pytest.CaptureFixture[str]
) -> None:
    register(ctx)
    parser = argparse.ArgumentParser()
    ctx.cli["switchyard"]["setup"](parser)
    args = parser.parse_args(["--json", "module", "list"])
    assert ctx.cli["switchyard"]["handler"](args) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "ext"


def test_idle_task_verifies_the_audit_chain(ctx: FakeCtx) -> None:
    register(ctx)
    summary = ctx.idle["switchyard-audit-verify"]["fn"](SimpleNamespace(name="switchyard-audit-verify"))
    assert summary.startswith("audit ok")


def test_driver_thread_ticks_only_in_the_hosting_process(ctx: FakeCtx, tmp_path: Path) -> None:
    register(ctx)
    adapter = adapter_mod.current()
    assert adapter.core.hosting and adapter.driver_alive()
    other = HermesAdapter(FakeCtx(ctx.state.data_dir))
    other.register()
    try:
        assert not other.core.hosting and not other.driver_alive()
        out = json.loads(
            other.ctx.tools["switchyard_modules"]["handler"]({"action": "activate", "id": "ext"})
        )
        assert out["ok"] is False and "does not host" in out["message"]
    finally:
        other.close()


def test_data_dir_setting_overrides_plugin_data(tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    fake = FakeCtx(tmp_path / "plugin-data", settings={"data_dir": str(custom)})
    try:
        register(fake)
        assert adapter_mod.current().core.data_dir == custom
    finally:
        adapter_mod.shutdown()


def test_hooks_and_middleware_are_forwarded_to_the_bridge(
    ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(ctx)
    assert set(ctx.hooks) == {
        "pre_llm_call",
        "pre_api_request",
        "post_api_request",
        "api_request_error",
        "post_llm_call",
        "subagent_stop",
    }
    assert set(ctx.middleware) == {"llm_request"}
    assert ctx.middleware["llm_request"](request={"model": "x"}, provider="p") is None  # no module changed it
    ctx.hooks["post_api_request"](model="x", usage={})  # no subscribers: no error
    bridge = adapter_mod.current().core.bridge
    monkeypatch.setattr(bridge, "dispatch_llm_request", lambda r, c: {**r, "model": "y"})
    assert ctx.middleware["llm_request"](request={"model": "x"}) == {"request": {"model": "y"}}
    assert ctx.middleware["llm_request"](request="not a dict") is None

    def broken(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("bridge bug")

    monkeypatch.setattr(bridge, "dispatch_hook", broken)
    monkeypatch.setattr(bridge, "dispatch_llm_request", broken)
    ctx.hooks["pre_llm_call"](user_message="hi")  # swallowed: never breaks a Hermes turn
    assert ctx.middleware["llm_request"](request={"model": "x"}) is None


def test_config_port_uses_the_public_hermes_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    from switchyard.hermes.config_port import HermesConfigAdapter

    stored: dict[str, Any] = {"skills": {"disabled": ["a"]}, "model": "m"}
    saved: list[tuple[dict[str, Any], bool]] = []
    config_mod = types.ModuleType("hermes_cli.config")
    config_mod.load_config = lambda: json.loads(json.dumps(stored))  # type: ignore[attr-defined]
    config_mod.save_config = lambda cfg, merge_existing=False: saved.append((cfg, merge_existing))  # type: ignore[attr-defined]
    tools_mod = types.ModuleType("tools.skills_tool")
    tools_mod.find_all_skills = lambda skip_disabled=False: [
        {"name": "a", "category": "c", "description": "d"}
    ]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_mod)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.skills_tool", tools_mod)
    port = HermesConfigAdapter()
    assert port.get("skills.disabled") == ["a"] and port.get("model.default") is None
    port.set("plugins.disabled", ["x"])
    assert saved[-1] == ({"skills": {"disabled": ["a"]}, "model": "m", "plugins": {"disabled": ["x"]}}, True)
    port.set("skills.disabled", [])
    assert saved[-1][0]["skills"] == {"disabled": []}
    assert port.skills() == [{"name": "a", "category": "c", "description": "d"}]
    assert port.essential() == frozenset({"hermes-agent"})  # agent.skill_utils not importable here
    skill_utils = types.ModuleType("agent.skill_utils")
    skill_utils.ESSENTIAL_SKILLS = {"hermes-agent", "other"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.skill_utils", skill_utils)
    assert port.essential() == frozenset({"hermes-agent", "other"})


def test_pre_llm_call_gate_blocks_the_turn(ctx: FakeCtx, monkeypatch: pytest.MonkeyPatch) -> None:
    register(ctx)
    bridge = adapter_mod.current().core.bridge
    assert ctx.hooks["pre_llm_call"](user_message="hi") is None
    monkeypatch.setattr(bridge, "dispatch_gate", lambda kw: "[switchyard/router] stop")
    assert ctx.hooks["pre_llm_call"](user_message="hi") == {
        "action": "block",
        "message": "[switchyard/router] stop",
    }
    assert ctx.hooks["post_llm_call"](user_message="hi") is None  # only pre_llm_call can block
