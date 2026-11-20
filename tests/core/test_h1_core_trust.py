"""H1 WP6: core trust layer (findings A-1, A-3, A-4, A-6, A-7, A-15, A-18, A-19, A-21, A-22, C-15)."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest
from sy_testing import write_module

from switchyard.contract import run_contract
from switchyard.core import Core
from switchyard.errors import CapabilityDenied, ManifestError
from switchyard.manifest import load_manifest, validate_file
from switchyard.paths import data_dir_source, resolve_data_dir
from switchyard.secrets import MemoryBackend, SecretUnavailable

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "module"
SECRET = "Zq9-canary-VALUE-7731-long"  # noqa: S105  # synthetic canary


# A-1: an explicit data directory wins over SWITCHYARD_DATA_DIR ------------------------------------------


def test_h1_a1_explicit_data_dir_beats_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_dir, arg_dir = tmp_path / "env", tmp_path / "arg"
    monkeypatch.setenv("SWITCHYARD_DATA_DIR", str(env_dir))
    assert resolve_data_dir(configured=arg_dir) == arg_dir
    assert "--data-dir" in data_dir_source(configured=arg_dir)
    assert resolve_data_dir(hermes_dir=tmp_path / "h") == env_dir  # the variable still beats the profile dir
    with Core(data_dir=arg_dir, hosting=True) as c:
        assert c.data_dir == arg_dir
    assert (arg_dir / "state.db").exists() and not env_dir.exists()
    assert run_contract(TEMPLATE, bundled=True).ok
    assert not env_dir.exists()  # the contract touched nothing outside its temporary directory


# A-3: the file that runs is the file that was checked --------------------------------------------------


def test_h1_a3_entry_shadowed_by_a_package_is_rejected(tmp_path: Path) -> None:
    d = write_module(tmp_path, "shadow")
    (d / "mod").mkdir()
    (d / "mod" / "__init__.py").write_text("RAN = True\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="both"):
        load_manifest(d)


def test_h1_a3_loaded_module_must_come_from_inside(tmp_path: Path) -> None:
    inside, outside = tmp_path / "m", tmp_path / "elsewhere"
    for p in (inside, outside):
        p.mkdir()
        (p / "x.py").write_text("", encoding="utf-8")
    from switchyard.manifest import loaded_inside

    assert loaded_inside(type("M", (), {"__file__": str(inside / "x.py")}), inside)
    assert not loaded_inside(type("M", (), {"__file__": str(outside / "x.py")}), inside)
    assert not loaded_inside(type("M", (), {}), inside)


@pytest.mark.skipif(
    not hasattr(__import__("os"), "name") or __import__("os").name != "nt", reason="junctions"
)
def test_h1_a3_junction_package_does_not_run(tmp_path: Path) -> None:
    import _winapi  # type: ignore[import-not-found]

    root = tmp_path / "modules"
    write_module(root, "jx", request=("ui.panel",))
    outside = tmp_path / "outside_pkg"
    outside.mkdir()
    marker = tmp_path / "ran.txt"
    (outside / "__init__.py").write_text(f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8")
    # mod.py stays (the reviewed file); the junction mod/ -> outside is what Python would import first
    _winapi.CreateJunction(str(outside), str(root / "jx" / "mod"))
    with Core(data_dir=tmp_path / "d", trusted_roots=[root], module_roots=[root], hosting=True) as c:
        if "jx" in c.manager.ids():
            c.run("module", "grant", {"id": "jx", "capability": "ui.panel"}, actor="t")
            c.run("module", "activate", {"id": "jx"}, actor="t")
            assert c.manager.info("jx").status.value != "active"
    assert not marker.exists()


# A-4: the contract checks the production trust rule ---------------------------------------------------


def test_h1_a4_contract_fails_an_in_process_module_outside_the_bundled_roots(tmp_path: Path) -> None:
    copy = tmp_path / "example"
    shutil.copytree(TEMPLATE, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    report = run_contract(copy)
    assert not report.ok
    trust = next(c for c in report.checks if c.name == "trust")
    assert not trust.ok and "subprocess" in trust.detail
    assert run_contract(copy, bundled=True).ok  # the repository's own modules opt in explicitly


# A-6: a grant does not outlive the manifest that requested it -----------------------------------------


def test_h1_a6_dropped_capability_loses_its_stored_grant(tmp_path: Path) -> None:
    root = tmp_path / "modules"
    d = write_module(root, "wide", request=("ui.panel", "schedule"))
    with Core(data_dir=tmp_path / "d", trusted_roots=[root], module_roots=[root], hosting=True) as c:
        c.run("module", "grant", {"id": "wide", "capability": "schedule"}, actor="t")
    toml = d / "module.toml"
    wide = toml.read_text(encoding="utf-8")
    toml.write_text(wide.replace('"ui.panel", "schedule"', '"ui.panel"'), encoding="utf-8")
    with Core(data_dir=tmp_path / "d", trusted_roots=[root], module_roots=[root], hosting=True):
        pass
    toml.write_text(wide, encoding="utf-8")
    with Core(data_dir=tmp_path / "d", trusted_roots=[root], module_roots=[root], hosting=True) as c:
        assert "schedule" not in c.policy.granted("wide")
        revoked = [r for r in c.run("audit", "tail", {"n": 50}, actor="t") if r["action"] == "policy.revoked"]
        assert revoked and revoked[-1]["detail"]["capability"] == "schedule"
        assert revoked[-1]["detail"]["reason"] == "no longer requested"


# A-7: secret values never leave through operation results ---------------------------------------------

LEAKY = """
class Mod:
    def activate(self, ctx):
        self.box = []
        ctx.secrets.use("secret://api.key", self.box.append)  # smuggled out past use()'s return check
        ctx.register_panel("leak.status", lambda: {"v": self.box[0]})
    def deactivate(self):
        pass
    def health(self):
        return (True, "detail " + self.box[0])
"""


def test_h1_a7_health_and_panel_results_are_redacted(tmp_path: Path) -> None:
    root = tmp_path / "modules"
    d = write_module(root, "leak", LEAKY, request=("ui.panel", "secrets.read"))
    toml = d / "module.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8")
        .replace("[contributes]", 'secrets = ["api.key"]\n[contributes]')
        .replace('panels = ["leak.status"]', 'panels = ["leak.status"]'),
        encoding="utf-8",
    )
    backend = MemoryBackend({"api.key": SECRET})
    with Core(data_dir=tmp_path / "d", trusted_roots=[root], module_roots=[root], hosting=True,
              secret_backends=[backend]) as c:  # fmt: skip
        for cap in ("ui.panel", "secrets.read"):
            c.run("module", "grant", {"id": "leak", "capability": cap}, actor="t")
        c.run("module", "activate", {"id": "leak"}, actor="t")
        assert c.manager.info("leak").error is None
        health = c.run("module", "health", {"id": "leak"}, actor="t")
        panel = c.run("module", "panel", {"id": "leak", "panel": "leak.status"}, actor="t")
    assert SECRET not in repr(health) and "[REDACTED]" in health["detail"]
    assert SECRET not in repr(panel)


# A-15: a module unregistered mid-check is denied, not a KeyError --------------------------------------


def test_h1_a15_require_host_after_unregister_is_denied(tmp_path: Path) -> None:
    from switchyard.capabilities import PolicyEngine

    class Store:
        def load(self, mid: str) -> frozenset[str]:
            return frozenset({"net.outbound", "secrets.read"})

    class Audit:
        def append(self, **kw: Any) -> None:
            pass

    engine = PolicyEngine(Store(), Audit())  # type: ignore[arg-type]
    gate = threading.Event()
    original = engine.require

    def racing(module_id: str, capability: str, **detail: str) -> None:
        gate.set()
        engine._modules.pop(module_id, None)  # the unregister lands between the check and the lookup
        if capability == "__never__":
            original(module_id, capability, **detail)

    engine.require = racing  # type: ignore[method-assign]
    engine._modules["m"] = object()  # type: ignore[assignment]
    with pytest.raises(CapabilityDenied):
        engine.require_host("m", "example.com")
    engine._modules["m"] = object()  # type: ignore[assignment]
    with pytest.raises(CapabilityDenied):
        engine.require_secret("m", "api.key")


# A-18: a backend error never carries its message (which may hold the value) to the caller -------------


def test_h1_a18_backend_errors_are_reduced_to_their_class(tmp_path: Path) -> None:
    class Broken:
        name = "broken"

        def available(self) -> bool:
            return True

        def get(self, name: str) -> str:
            raise OSError("keyring unlock failed; token=TOKEN-ABCDEFGH-12345")

    root = tmp_path / "modules"
    d = write_module(root, "reader", request=("secrets.read",))
    toml = d / "module.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace("[contributes]", 'secrets = ["api.key"]\n[contributes]'),
        encoding="utf-8",
    )
    with Core(data_dir=tmp_path / "d", trusted_roots=[root], module_roots=[root], hosting=True,
              secret_backends=[Broken()]) as c:  # fmt: skip
        c.run("module", "grant", {"id": "reader", "capability": "secrets.read"}, actor="t")
        with pytest.raises(SecretUnavailable) as info:
            c.secrets.use("reader", "secret://api.key", lambda v: v)
        assert "TOKEN" not in str(info.value) and "OSError" in str(info.value)
        records = [
            r for r in c.run("audit", "tail", {"n": 20}, actor="t") if r["action"] == "secret.backend_error"
        ]
        assert records and records[-1]["detail"] == {
            "secret": "api.key",
            "backend": "broken",
            "error": "OSError",
        }


# A-19: the validator checks the policies grammar ------------------------------------------------------


def test_h1_a19_validator_rejects_unsupported_policies(tmp_path: Path) -> None:
    d = write_module(tmp_path, "pol")
    toml = d / "module.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace(
            "[contributes]", '[contributes]\npolicies = ["allow:fs.read"]'
        ),
        encoding="utf-8",
    )
    assert any("policy" in e for e in validate_file(toml))


# A-21: the contract's "grants gone" check reads the store ---------------------------------------------


def test_h1_a21_contract_detects_grants_left_in_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    from switchyard.capabilities import PolicyEngine

    real = PolicyEngine.unregister

    def keeps(self: PolicyEngine, module_id: str, *, actor: str, keep_grants: bool = False) -> None:
        real(self, module_id, actor=actor, keep_grants=True)  # regression: grants left behind

    monkeypatch.setattr(PolicyEngine, "unregister", keeps)
    report = run_contract(TEMPLATE, bundled=True)
    remove = next(c for c in report.checks if c.name == "remove")
    assert not remove.ok and "grants" in remove.detail


# A-22: one failing cleanup step does not skip the others ---------------------------------------------


def test_h1_a22_context_close_runs_every_step(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from switchyard.context import ModuleContext

    calls: list[str] = []

    def step(name: str, fail: bool = False) -> Any:
        def run(module_id: str) -> None:
            calls.append(name)
            if fail:
                raise RuntimeError(name)

        return run

    services = SimpleNamespace(
        panels=SimpleNamespace(remove_all=step("panels", fail=True)),
        bus=SimpleNamespace(unsubscribe_all=step("bus", fail=True)),
        actions=SimpleNamespace(remove_all=step("actions")),
        secret_backends=SimpleNamespace(remove_backends=step("backends")),
        bridge=SimpleNamespace(remove_all=step("bridge")),
    )
    ctx = ModuleContext.__new__(ModuleContext)
    ctx._manifest, ctx._closed, ctx._services = SimpleNamespace(id="m"), False, services  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        ctx.close()
    assert calls == ["panels", "bus", "actions", "backends", "bridge"]
    ctx.close()  # idempotent
    assert len(calls) == 5


# C-15: bw output loses its trailing newline ------------------------------------------------------------


def test_h1_c15_bitwarden_strips_one_trailing_newline() -> None:
    import json

    from switchyard.modules.secrets import backends as B

    unlocked = subprocess.CompletedProcess([], 0, json.dumps({"status": "unlocked"}), "")
    results = [unlocked, subprocess.CompletedProcess([], 0, SECRET + "\n", "")]
    bw = B.BitwardenBackend(lambda argv, **kw: results.pop(0), environ={"BW_SESSION": "s" * 10})
    assert bw.get("api.key") == SECRET
