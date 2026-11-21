"""M0 acceptance tests (docs/qa/01-m0-prework.md section 4), end to end through the public surfaces."""

from __future__ import annotations

import functools
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from switchyard import cli
from switchyard import hermes as hermes_mod
from switchyard.api import ApiClient, ControlServer
from switchyard.core import Core
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.secrets import MemoryBackend

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "module"
CANARY = "canary-" + "acc3pt4nce-value"
URL = "https://example.invalid/vendor/example.git"
GOOD_SHA, BAD_SHA, PIN = "a" * 40, "b" * 40, "c" * 40

PROBE = """
class Mod:
    def __init__(self):
        self.ctx = None
        self.length = None

    def activate(self, ctx):
        self.ctx = ctx
        self.length = ctx.secrets.use("secret://provider.key", len)
        ctx.log("probe", "secret used", length=self.length)
        ctx.register_panel("probe.status", lambda: {"length": self.length})
        ctx.register_panel("probe.leak", lambda: ctx.secrets.use("secret://provider.key", lambda v: {"v": v}))
        ctx.register_panel("probe.raise", self._raise)
        ctx.register_panel("probe.net", lambda: repr(ctx.net))

    def _raise(self):
        def bad(value):
            raise RuntimeError("value is " + value)
        return self.ctx.secrets.use("secret://provider.key", bad)

    def deactivate(self):
        self.ctx = None

    def health(self):
        return (self.ctx is not None, "ok")
"""

PROBE_TOML = """schema = 1
[module]
id = "probe"
name = "Probe"
version = "0.1.0"
license = "Apache-2.0"
license_class = "open"
summary = "acceptance probe"
requires_core = ">=0.1,<1"
isolation = "in-process"
entry = "mod:Mod"
[capabilities]
request = ["ui.panel", "secrets.read"]
secrets = ["provider.key"]
[contributes]
panels = ["probe.status", "probe.leak", "probe.raise", "probe.net"]
log_streams = ["probe"]
[lifecycle]
activation = "manual"
"""


def _copy_template(
    dest: Path,
    *,
    isolation: str = "in-process",
    version: str = "0.1.0",
    git: bool = False,
    health_ok: bool = True,
) -> Path:
    shutil.copytree(TEMPLATE, dest, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    toml = dest / "module.toml"
    text = toml.read_text(encoding="utf-8")
    text = text.replace('isolation = "in-process"', f'isolation = "{isolation}"')
    text = text.replace('version = "0.1.0"', f'version = "{version}"')
    if git:
        text = text.replace('source = "bundled"', f'source = "git"\nurl = "{URL}"\nref = "{PIN}"')
    toml.write_text(text, encoding="utf-8")
    if not health_ok:
        code = dest / "example.py"
        code.write_text(
            code.read_text(encoding="utf-8").replace("ok=self._ctx is not None", "ok=False"), encoding="utf-8"
        )
    return dest


class Fetcher:
    def __init__(self, sources: dict[str, Path]) -> None:
        self.sources = sources

    def fetch(self, url: str, ref: str, dest: Path) -> None:
        assert url == URL
        shutil.copytree(self.sources[ref], dest)


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


def _actions(core: Core) -> list[str]:
    return [r["action"] for r in core.run("audit", "tail", {"n": 1000}, actor="t")]


# 1, 2, 3, 4 -----------------------------------------------------------------------------------------------


def test_template_lifecycle_denial_update_rollback_and_audit(tmp_path: Path) -> None:
    data = tmp_path / "data"
    modules = data / "modules"
    _copy_template(modules / "example", git=True)
    sources = {
        GOOD_SHA: _copy_template(tmp_path / "v2" / "example", version="0.2.0", git=True),
        BAD_SHA: _copy_template(tmp_path / "v3" / "example", version="0.3.0", git=True, health_ok=False),
    }
    with Core(data_dir=data, trusted_roots=[modules], fetcher=Fetcher(sources), hosting=True) as core:
        # 1. discovered, verified, granted, loaded, activated
        assert core.run("module", "show", {"id": "example"}, actor="cli")["status"] == "verified"
        core.run("module", "grant", {"id": "example", "capability": "ui.panel"}, actor="cli")
        core.run("module", "activate", {"id": "example"}, actor="cli")
        assert core.run("module", "show", {"id": "example"}, actor="cli")["status"] == "active"
        assert core.run("module", "panel", {"id": "example", "panel": "example.status"}, actor="cli") == {
            "title": "Example",
            "state": "active",
        }
        # 2. an ungranted capability is denied and audited
        with pytest.raises(CapabilityDenied):
            core.policy.require("example", "net.outbound")
        assert _actions(core).count("policy.denied") == 1
        # 4. update to a pinned commit; a failing health check rolls back; the core keeps running
        assert core.run("module", "update", {"id": "example", "ref": GOOD_SHA}, actor="cli")["to"] == "0.2.0"
        result = core.run("module", "update", {"id": "example", "ref": BAD_SHA}, actor="cli")
        assert result["rolled_back"] is True
        show = core.run("module", "show", {"id": "example"}, actor="cli")
        assert show["version"] == "0.2.0" and show["status"] == "active"
        assert core.run("module", "health", {"id": "example"}, actor="cli")["ok"] is True
        # 3. every grant, activation, denial, update and rollback is audited, and the chain verifies
        actions = _actions(core)
        for wanted in (
            "policy.granted",
            "module.activated",
            "policy.denied",
            "module.updated",
            "module.rolled_back",
        ):
            assert wanted in actions, wanted
        assert core.run("audit", "verify", {}, actor="cli")["ok"] is True

    # 3. ...and fails after any edit
    log = sorted((data / "audit").glob("*.jsonl"))[-1]
    lines = log.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[3])
    record["actor"] = "someone-else"
    lines[3] = json.dumps(record, separators=(",", ":"), sort_keys=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with Core(data_dir=data, trusted_roots=[modules], hosting=False) as reopened:
        assert reopened.run("audit", "verify", {}, actor="cli")["ok"] is False
        assert reopened.audit_status.ok is False


# 5 and 6 --------------------------------------------------------------------------------------------------


class FakeHermesCtx:
    def __init__(self, data_dir: Path) -> None:
        self.state = SimpleNamespace(data_dir=data_dir)
        self.tools: dict[str, Any] = {}
        self.commands: dict[str, Any] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return default

    def register_tool(self, name: str, toolset: str, schema: Any, handler: Any, **_kw: Any) -> None:
        self.tools[name] = handler

    def register_command(self, name: str, handler: Any, **_kw: Any) -> None:
        self.commands[name] = handler

    def register_cli_command(self, *_a: Any, **_kw: Any) -> None:
        pass

    def register_idle_task(self, *_a: Any, **_kw: Any) -> None:
        pass

    def register_redaction_patterns(self, patterns: list[str]) -> int:
        return len(patterns)

    def register_hook(self, *_a: Any, **_kw: Any) -> None:
        pass

    def register_middleware(self, *_a: Any, **_kw: Any) -> None:
        pass


@pytest.fixture
def surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Path, FakeHermesCtx, ApiClient]]:
    data = tmp_path / "plugin-data"
    modules = data / "modules"
    _copy_template(modules / "example", isolation="subprocess")
    probe = modules / "probe"
    probe.mkdir()
    (probe / "mod.py").write_text(PROBE, encoding="utf-8")
    (probe / "module.toml").write_text(PROBE_TOML, encoding="utf-8")
    backend = MemoryBackend({"provider.key": CANARY}, allow_test_backend=True)
    monkeypatch.setattr(
        hermes_mod, "Core", functools.partial(Core, trusted_roots=[modules], secret_backends=[backend])
    )
    ctx = FakeHermesCtx(data)
    hermes_mod.register(ctx)
    core = hermes_mod.current().core
    assert core.hosting
    server = ControlServer(core)
    server.start()
    try:
        yield data, ctx, ApiClient.from_data_dir(data)
    finally:
        server.shutdown()
        hermes_mod.shutdown()


def _cli(data: Path, capsys: pytest.CaptureFixture[str], *args: str) -> Any:
    code = cli.main(["--data-dir", str(data), "--json", *args])
    out = capsys.readouterr().out
    assert code == 0, out
    return json.loads(out)


def _slash(ctx: FakeHermesCtx, line: str) -> Any:
    reply = ctx.commands["switchyard"](line)
    assert not reply.startswith("error"), reply
    return json.loads(reply)


def _tool(ctx: FakeHermesCtx, **args: Any) -> Any:
    out = json.loads(ctx.tools["switchyard_modules"](args))
    assert out["ok"], out
    return out["result"]["untrusted_data"]  # module text reaches the model labelled as data (R1)


def test_same_operations_from_cli_api_and_hermes(
    surfaces: tuple[Path, FakeHermesCtx, ApiClient], capsys: pytest.CaptureFixture[str]
) -> None:
    data, ctx, api = surfaces
    # list: identical from every surface
    listings = [
        _cli(data, capsys, "module", "list"),
        api.request("module", "list", {}),
        _tool(ctx, action="list"),
    ]
    assert listings[0] == listings[1] == listings[2]
    assert {m["id"] for m in listings[0]} == {"example", "probe"}

    def mode() -> list[str]:
        return [
            next(m["mode"] for m in _cli(data, capsys, "module", "list") if m["id"] == "example"),
            api.request("module", "show", {"id": "example"})["mode"],
            next(m["mode"] for m in _tool(ctx, action="list") if m["id"] == "example"),
        ]

    # disable / enable (operation `module mode`): from the CLI, the API and Hermes (/switchyard: human path)
    _cli(data, capsys, "module", "mode", "example", "--mode", "disabled")
    assert mode() == ["disabled"] * 3
    api.request("module", "mode", {"id": "example", "mode": "manual"})
    assert mode() == ["manual"] * 3
    _slash(ctx, "module mode example mode=disabled")
    assert mode() == ["disabled"] * 3
    _slash(ctx, "module mode example mode=manual")
    # live operations go to the hosting process; the result is the same from the API and the Hermes tool
    api.request("module", "grant", {"id": "example", "capability": "ui.panel"})
    assert api.request("module", "activate", {"id": "example"})["status"] == "active"
    assert _tool(ctx, action="health", id="example") == api.request("module", "health", {"id": "example"})
    assert api.request("module", "deactivate", {"id": "example"})["status"] != "active"
    refused = json.loads(ctx.tools["switchyard_modules"]({"action": "deactivate", "id": "example"}))
    assert not refused["ok"]  # operator only (R1 review)


def test_secret_canary_never_appears_in_any_output(
    surfaces: tuple[Path, FakeHermesCtx, ApiClient], capsys: pytest.CaptureFixture[str]
) -> None:
    data, ctx, api = surfaces
    seen: list[str] = []
    for capability in ("ui.panel", "secrets.read"):
        seen.append(ctx.commands["switchyard"](f"module grant probe capability={capability}"))
    seen.append(ctx.commands["switchyard"]("module mode probe mode=auto"))  # H1 C-6: model starts auto only
    seen.append(ctx.tools["switchyard_modules"]({"action": "activate", "id": "probe"}))
    assert json.loads(seen[-1])["result"]["untrusted_data"]["status"] == "active"
    assert api.request("module", "panel", {"id": "probe", "panel": "probe.status"}) == {"length": len(CANARY)}
    for panel in ("probe.leak", "probe.raise", "probe.net"):
        seen.append(ctx.commands["switchyard"](f"module panel probe panel={panel}"))
        with pytest.raises(SwitchyardError) as info:
            api.request("module", "panel", {"id": "probe", "panel": panel})
        seen.append(str(info.value))
    assert any("contained the secret value" in s for s in seen)
    assert any("secret use failed: RuntimeError" in s for s in seen)
    assert any("net.outbound" in s for s in seen)
    for tool, args in (
        ("switchyard_modules", {"action": "list"}),
        ("switchyard_audit", {"action": "tail", "n": 500}),
        ("switchyard_host", {}),
    ):
        seen.append(ctx.tools[tool](args))
    seen.append(json.dumps(_cli(data, capsys, "audit", "tail", "--n", "500")))
    seen.append(ctx.tools["switchyard_modules"]({"action": "deactivate", "id": "probe"}))
    for text in seen:
        assert CANARY not in text
    # every file the core wrote: logs, audit log, state database, API files (host.lock holds a PID and is
    # byte-locked by the hosting process on Windows)
    for path in data.rglob("*"):
        if path.is_file() and "modules" not in path.relative_to(data).parts and path.name != "host.lock":
            assert CANARY.encode() not in path.read_bytes(), path
    assert any("secret used" in p.read_text(encoding="utf-8") for p in (data / "logs").rglob("*.jsonl"))
