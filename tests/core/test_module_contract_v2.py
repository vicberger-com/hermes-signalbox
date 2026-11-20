"""ADR-0002: module-provided secret backends and module actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sy_testing import write_module

from switchyard.core import Core
from switchyard.errors import SwitchyardError
from switchyard.ops import MODEL_ACTOR, UsageError

CANARY = "canary-" + "b4ck3nd-value"

PROVIDER = """
class Backend:
    name = "vault"
    def __init__(self):
        self.values = {"api.key": "%s"}
    def available(self):
        return True
    def get(self, name):
        return self.values[name]


class Mod:
    def activate(self, ctx):
        self.ctx = ctx
        ctx.provide_secret_backend(Backend())
        ctx.register_action("status", self.status, read_only=True)
        ctx.register_action("bump", self.bump, params={"by": int, "note": str, "loud": bool})
        ctx.register_action("leak", lambda: {"v": "%s"}, read_only=True)
        ctx.register_action("crash", self.crash)
    def status(self):
        return {"ok": True}
    def bump(self, by, note="", loud=False):
        return {"by": by, "note": note, "loud": loud}
    def crash(self):
        raise RuntimeError("detail that must not escape")
    def deactivate(self):
        pass
    def health(self):
        return True
""".replace("%s", CANARY)

USER = """
class Mod:
    def activate(self, ctx):
        self.length = ctx.secrets.use("secret://api.key", len)
        ctx.register_panel("{id}.status", lambda: {"length": self.length})
    def deactivate(self):
        pass
    def health(self):
        return True
"""


def _declare(d: Path, *, backends: list[str] | None = None, commands: list[str] | None = None) -> None:
    toml = d / "module.toml"
    text = toml.read_text(encoding="utf-8")
    extra = ""
    if backends is not None:
        extra += f"secret_backends = {json.dumps(backends)}\n"
    if commands is not None:
        extra += f"commands = {json.dumps(commands)}\n"
    toml.write_text(text.replace("[contributes]\n", "[contributes]\n" + extra), encoding="utf-8")


def _secrets_request(d: Path) -> None:
    toml = d / "module.toml"
    text = toml.read_text(encoding="utf-8")
    text = text.replace('request = ["secrets.read"]', 'request = ["secrets.read", "ui.panel"]')
    text = text.replace("[contributes]\n", "[contributes]\n")
    toml.write_text(
        text.replace("[capabilities]\n", '[capabilities]\nsecrets = ["api.key"]\n'), encoding="utf-8"
    )


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def core(tmp_path: Path) -> Any:
    root = tmp_path / "modules"
    prov = write_module(root, "prov", PROVIDER, request=("secrets.read",))
    _secrets_request(prov)
    _declare(prov, backends=["vault"], commands=["status", "bump", "leak", "crash"])
    user = write_module(root, "user", USER, request=("secrets.read", "ui.panel"))
    _secrets_request(user)
    c = Core(data_dir=tmp_path / "data", trusted_roots=[root], module_roots=[root], hosting=True)
    for mid in ("prov", "user"):
        for cap in ("secrets.read", "ui.panel"):
            if cap in c.manager.manifest(mid).requested:
                c.run("module", "grant", {"id": mid, "capability": cap}, actor="t")
    yield c
    c.close()


def test_trusted_module_provides_a_backend_other_modules_use(core: Core) -> None:
    core.run("module", "activate", {"id": "prov"}, actor="t")
    core.run("module", "activate", {"id": "user"}, actor="t")
    assert core.run("module", "show", {"id": "user"}, actor="t")["status"] == "active"
    assert core.run("module", "panel", {"id": "user", "panel": "user.status"}, actor="t") == {
        "length": len(CANARY)
    }
    core.run("module", "deactivate", {"id": "prov"}, actor="t")
    assert core.secrets.backend_names() == []  # removed with its module


def test_backend_needs_declaration_grant_and_in_process(core: Core, tmp_path: Path) -> None:
    core.run("module", "revoke", {"id": "prov", "capability": "secrets.read"}, actor="t")
    core.run("module", "activate", {"id": "prov"}, actor="t")
    assert core.run("module", "show", {"id": "prov"}, actor="t")["status"] == "failed"
    assert core.secrets.backend_names() == []


def test_undeclared_backend_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "modules"
    prov = write_module(root, "prov", PROVIDER, request=("secrets.read",))
    _secrets_request(prov)
    _declare(prov, backends=["other"], commands=["status", "bump", "leak", "crash"])
    with Core(data_dir=tmp_path / "data", trusted_roots=[root], module_roots=[root], hosting=True) as c:
        c.run("module", "grant", {"id": "prov", "capability": "secrets.read"}, actor="t")
        c.run("module", "activate", {"id": "prov"}, actor="t")
        info = c.run("module", "show", {"id": "prov"}, actor="t")
        assert info["status"] == "failed" and c.secrets.backend_names() == []


def test_subprocess_module_cannot_provide_a_backend(tmp_path: Path) -> None:
    from switchyard.context import ContextServices, ModuleContext
    from switchyard.manifest import load_manifest

    root = tmp_path / "modules"
    d = write_module(root, "ext", PROVIDER, request=("secrets.read",), isolation="subprocess")
    _secrets_request(d)
    _declare(d, backends=["vault"])
    ctx = ModuleContext(load_manifest(d), ContextServices(policy=None, logs=None, panels=None, bus=None))  # type: ignore[arg-type]
    with pytest.raises(SwitchyardError, match="in-process"):
        ctx.provide_secret_backend(object())


def test_actions_from_every_surface_with_validation(core: Core) -> None:
    core.run("module", "activate", {"id": "prov"}, actor="t")
    run = core.run
    assert run("module", "action", {"id": "prov", "action": "status"}, actor="t") == {"ok": True}
    assert run("module", "action", {"id": "prov", "action": "bump", "args": {"by": 2}}, actor="t") == {
        "by": 2, "note": "", "loud": False,
    }  # fmt: skip
    with pytest.raises(UsageError, match="must be int"):
        run("module", "action", {"id": "prov", "action": "bump", "args": {"by": "2"}}, actor="t")
    with pytest.raises(UsageError, match="unknown"):
        run("module", "action", {"id": "prov", "action": "bump", "args": {"by": 1, "x": 1}}, actor="t")
    with pytest.raises(UsageError, match="missing"):
        run("module", "action", {"id": "prov", "action": "bump"}, actor="t")
    with pytest.raises(SwitchyardError, match="unknown action"):
        run("module", "action", {"id": "prov", "action": "nope"}, actor="t")
    with pytest.raises(SwitchyardError) as info:
        run("module", "action", {"id": "prov", "action": "crash"}, actor="t")
    assert "must not escape" not in str(info.value) and "RuntimeError" in str(info.value)
    assert "module.action" in [r["action"] for r in run("audit", "tail", {"n": 50}, actor="t")]


def test_model_actor_runs_read_only_actions_only(core: Core) -> None:
    core.run("module", "activate", {"id": "prov"}, actor="t")
    assert core.run("module", "action", {"id": "prov", "action": "status"}, actor=MODEL_ACTOR) == {"ok": True}
    with pytest.raises(SwitchyardError, match="read-only"):
        core.run("module", "action", {"id": "prov", "action": "bump", "args": {"by": 1}}, actor=MODEL_ACTOR)


def test_action_results_are_redacted(core: Core) -> None:
    core.run("module", "activate", {"id": "prov"}, actor="t")
    core.run("module", "activate", {"id": "user"}, actor="t")  # the broker has now seen the value
    out = core.run("module", "action", {"id": "prov", "action": "leak"}, actor="t")
    assert CANARY not in json.dumps(out)


def test_actions_need_declaration_and_go_away_on_stop(core: Core, tmp_path: Path) -> None:
    core.run("module", "activate", {"id": "prov"}, actor="t")
    core.run("module", "deactivate", {"id": "prov"}, actor="t")
    with pytest.raises(SwitchyardError):
        core.run("module", "action", {"id": "prov", "action": "status"}, actor="t")


def test_action_surfaces_cli_slash_and_model_tool(core: Core, capsys: pytest.CaptureFixture[str]) -> None:
    from switchyard import cli
    from switchyard.hermes import HermesAdapter

    core.run("module", "activate", {"id": "prov"}, actor="t")
    adapter = HermesAdapter.__new__(HermesAdapter)
    adapter.core = core
    assert json.loads(adapter.command("module action prov bump by=3 loud=true note=hi")) == {
        "by": 3, "note": "hi", "loud": True,
    }  # fmt: skip
    out = json.loads(adapter.tool_modules({"action": "run", "id": "prov", "name": "status"}))
    assert out == {"ok": True, "result": {"ok": True}}
    out = json.loads(adapter.tool_modules({"action": "run", "id": "prov", "name": "bump", "args": {"by": 1}}))
    assert out["ok"] is False and "read-only" in out["message"]
    parser = cli._parser()
    ns = parser.parse_args(["module", "action", "prov", "--action", "bump", "--args", '{"by": 5}'])
    assert ns.args == {"by": 5}
    with pytest.raises(SystemExit):
        parser.parse_args(["module", "action", "prov", "--action", "bump", "--args", "[1]"])
    with pytest.raises(SystemExit):
        parser.parse_args(["module", "action", "prov", "--action", "bump", "--args", "{bad"])
    capsys.readouterr()


def test_duplicate_backend_name_is_refused(core: Core) -> None:
    class B:
        name = "vault"

    core.run("module", "activate", {"id": "prov"}, actor="t")
    with pytest.raises(SwitchyardError, match="already provided"):
        core.secrets.add_backend("other", B())


def test_action_registration_rules(core: Core, tmp_path: Path) -> None:
    from switchyard.context import ContextServices, ModuleContext

    manifest = core.manager.manifest("prov")
    bare = ModuleContext(manifest, ContextServices(policy=core.policy, logs=None, panels=None, bus=None))  # type: ignore[arg-type]
    with pytest.raises(SwitchyardError, match="not declared"):
        bare.register_action("undeclared", lambda: None)
    with pytest.raises(SwitchyardError, match="bool, int or str"):
        bare.register_action("status", lambda: None, params={"x": float})
    with pytest.raises(SwitchyardError, match="not available"):
        bare.register_action("status", lambda: None)
    core.run("module", "activate", {"id": "prov"}, actor="t")
    with pytest.raises(SwitchyardError, match="broker is not available"):

        class V:
            name = "vault"

        bare.provide_secret_backend(V())
