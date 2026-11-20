"""M1 secrets module: backends through the core broker, metadata, rotation, expiry, contract suite."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from switchyard.contract import run_contract
from switchyard.core import BUILTIN_MODULES, Core
from switchyard.errors import SwitchyardError

pytestmark = pytest.mark.bundled_modules

MODULE_DIR = Path(BUILTIN_MODULES) / "secrets"
CANARY = "canary-" + "m1s3cr3t-value"
CONSUMER = """
class Mod:
    def activate(self, ctx):
        self.n = ctx.secrets.use("secret://api.key", len)
        ctx.register_panel("consumer.status", lambda: {"n": self.n})
    def deactivate(self):
        pass
    def health(self):
        return True
"""


def _backends_module() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("m1_backends", MODULE_DIR / "backends.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _backends_module()


def _write_consumer(root: Path) -> None:
    d = root / "consumer"
    d.mkdir(parents=True)
    (d / "mod.py").write_text(CONSUMER, encoding="utf-8")
    (d / "module.toml").write_text(
        """schema = 1
[module]
id = "consumer"
name = "consumer"
version = "0.1.0"
license = "Apache-2.0"
license_class = "open"
summary = "test"
requires_core = ">=0.1,<1"
isolation = "in-process"
entry = "mod:Mod"
[capabilities]
request = ["secrets.read", "ui.panel"]
secrets = ["api.key"]
[contributes]
panels = ["consumer.status"]
[lifecycle]
activation = "manual"
""",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)
    monkeypatch.setenv(B.EnvBackend.variable("api.key"), CANARY)


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.toml").write_text('[modules.secrets]\nbackends = ["env"]\nallow_env_backend = true\n',
                                      encoding="utf-8")  # fmt: skip
    extra = tmp_path / "extra"
    _write_consumer(extra)
    c = Core(data_dir=data, trusted_roots=[BUILTIN_MODULES, extra], module_roots=[BUILTIN_MODULES, extra],
             hosting=True)  # fmt: skip
    for mid, caps in (
        ("secrets", ("secrets.read", "process.spawn", "ui.panel")),
        ("consumer", ("secrets.read", "ui.panel")),
    ):
        for cap in caps:
            c.run("module", "grant", {"id": mid, "capability": cap}, actor="t")
    yield c
    c.close()


def test_secrets_module_passes_the_contract_suite() -> None:
    # CI runners may lack the OS store (no secret-tool on Linux), so the contract uses the env backend.
    report = run_contract(MODULE_DIR, settings={"backends": ["env"], "allow_env_backend": True})
    assert report.ok, report.summary()


def test_backend_serves_other_modules_and_canary_stays_hidden(core: Core) -> None:
    core.run("module", "activate", {"id": "secrets"}, actor="t")
    core.run("module", "activate", {"id": "consumer"}, actor="t")
    assert core.run("module", "panel", {"id": "consumer", "panel": "consumer.status"}, actor="t") == {
        "n": len(CANARY)
    }
    status = core.run("module", "action", {"id": "secrets", "action": "status"}, actor="hermes")
    assert status["backends"] == [{"name": "env", "available": True, "writable": False}]
    assert core.run("module", "health", {"id": "secrets"}, actor="t")["ok"] is True
    blob = json.dumps([status, core.run("audit", "tail", {"n": 500}, actor="t")])
    assert CANARY not in blob
    for path in core.data_dir.rglob("*"):
        if path.is_file() and path.name != "host.lock":
            assert CANARY.encode() not in path.read_bytes(), path


def test_env_backend_is_refused_by_default(tmp_path: Path) -> None:
    with Core(data_dir=tmp_path / "d", hosting=True) as c:
        (c.data_dir / "config.toml").write_text('[modules.secrets]\nbackends = ["env"]\n', encoding="utf-8")
    with Core(data_dir=tmp_path / "d", hosting=True) as c:
        for cap in ("secrets.read", "process.spawn", "ui.panel"):
            c.run("module", "grant", {"id": "secrets", "capability": cap}, actor="t")
        c.run("module", "activate", {"id": "secrets"}, actor="t")
        assert c.run("module", "show", {"id": "secrets"}, actor="t")["status"] == "failed"
        assert c.secrets.backend_names() == []


def test_expire_and_status_report_by_name(core: Core) -> None:
    core.run("module", "activate", {"id": "secrets"}, actor="t")
    act = {"id": "secrets", "action": "expire", "args": {"name": "api.key", "date": "2000-01-01"}}
    assert core.run("module", "action", act, actor="t") == {"name": "api.key", "expires_at": "2000-01-01"}
    rows = core.run("module", "action", {"id": "secrets", "action": "status"}, actor="t")["secrets"]
    assert rows[0]["name"] == "api.key" and rows[0]["expiring"] is True
    assert "expiring soon: api.key" in core.run("module", "health", {"id": "secrets"}, actor="t")["detail"]
    assert "module.secrets.expiry_set" in [
        r["action"] for r in core.run("audit", "tail", {"n": 50}, actor="t")
    ]
    for bad in ({"name": "api.key", "date": "2000-13-01"}, {"name": "api.key", "date": "soon"},
                {"name": "Bad Name", "date": "2000-01-01"}):  # fmt: skip
        with pytest.raises(SwitchyardError):
            core.run("module", "action", {"id": "secrets", "action": "expire", "args": bad}, actor="t")
    with pytest.raises(SwitchyardError, match="read-only"):
        core.run("module", "action", act, actor="hermes")


def test_rotate_without_a_writable_backend_fails(core: Core) -> None:
    core.run("module", "activate", {"id": "secrets"}, actor="t")
    with pytest.raises(SwitchyardError, match="no writable"):
        core.run(
            "module", "action", {"id": "secrets", "action": "rotate", "args": {"name": "api.key"}}, actor="t"
        )


@pytest.mark.parametrize(
    "setting",
    [
        'backends = "env"',
        "rotation_length = 8",
        "expiry_warning_days = -1",
        "colour = 1",
        'backends = ["nope"]',
    ],
)
def test_bad_settings_fail_activation(tmp_path: Path, setting: str) -> None:
    data = tmp_path / "d"
    data.mkdir()
    (data / "config.toml").write_text(f"[modules.secrets]\n{setting}\n", encoding="utf-8")
    with Core(data_dir=data, hosting=True) as c:
        for cap in ("secrets.read", "process.spawn", "ui.panel"):
            c.run("module", "grant", {"id": "secrets", "capability": cap}, actor="t")
        c.run("module", "activate", {"id": "secrets"}, actor="t")
        assert c.run("module", "show", {"id": "secrets"}, actor="t")["status"] == "failed"


# rotation logic with a fake writable backend ----------------------------------------------------------------


class FakeState:
    def __init__(self) -> None:
        import sqlite3

        self.db = sqlite3.connect(":memory:")

    def create_table(self, name: str, cols: list[tuple[str, str]], primary_key: list[str]) -> None:
        spec = ", ".join(f"{c} {t}" for c, t in cols)
        self.db.execute(
            f"CREATE TABLE IF NOT EXISTS m_{name} ({spec}, PRIMARY KEY ({', '.join(primary_key)}))"
        )

    def table(self, name: str) -> str:
        return f"m_{name}"

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        return self.db.execute(sql, params).fetchall()


class Writable:
    name = "vault"

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def get(self, name: str) -> str:
        return self.values[name]

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


def _module_with(backends: list[Any]) -> Any:
    m = _load_secrets_module().SecretsModule()
    events: list[tuple[str, dict[str, str]]] = []
    m.ctx = SimpleNamespace(
        state=FakeState(), log=lambda *a, **k: None, audit=lambda e, **d: events.append((e, d))
    )
    m.ctx.state.create_table("meta", [("name", "TEXT"), ("backend", "TEXT"), ("created_at", "TEXT"),
                                      ("rotated_at", "TEXT"), ("expires_at", "TEXT")], ["name"])  # fmt: skip
    m.backends = backends
    m.settings = {"rotation_length": 32, "expiry_warning_days": 14}
    m.events = events
    return m


def _load_secrets_module() -> Any:
    import importlib.util
    import types

    pkg = types.ModuleType("m1pkg")
    pkg.__path__ = [str(MODULE_DIR)]
    sys.modules["m1pkg"] = pkg
    spec = importlib.util.spec_from_file_location("m1pkg.secrets_module", MODULE_DIR / "secrets_module.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["m1pkg.secrets_module"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_rotate_writes_a_new_value_and_never_returns_it() -> None:
    vault = Writable()
    m = _module_with([vault])
    first = m.rotate("db.password")
    value1 = vault.values["db.password"]
    assert len(value1) >= 40 and value1 not in json.dumps(first)
    second = m.rotate("db.password")
    assert vault.values["db.password"] != value1 and second["backend"] == "vault"
    row = m.status()["secrets"][0]
    assert row["name"] == "db.password" and row["rotated_at"] and row["age_days"] == 0
    assert [e for e, _ in m.events] == ["rotated", "rotated"]
    assert all(vault.values["db.password"] not in json.dumps(d) for _, d in m.events)
    with pytest.raises(SwitchyardError, match="no writable"):
        m.rotate("db.password", backend="other")


# backend units with fake runners -------------------------------------------------------------------------


def _done(code: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


class FakeRun:
    def __init__(self, *results: subprocess.CompletedProcess[str]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"argv": argv, **kw})
        return self.results.pop(0)


def test_keychain_backend() -> None:
    run = FakeRun(_done(0, CANARY + "\n"), _done(44), _done(51))
    k = B.KeychainBackend(run)
    assert k.get("api.key") == CANARY
    with pytest.raises(KeyError):
        k.get("missing")
    with pytest.raises(B.SecretLocked):
        k.get("api.key")
    assert run.calls[0]["argv"] == [
        "security",
        "find-generic-password",
        "-s",
        "switchyard",
        "-a",
        "api.key",
        "-w",
    ]
    assert not hasattr(k, "set")


def test_secret_tool_backend_reads_and_writes_through_stdin() -> None:
    run = FakeRun(_done(0, CANARY), _done(1, ""), _done(1, "", "dbus"), _done(0), _done(3))
    s = B.SecretToolBackend(run)
    assert s.get("api.key") == CANARY
    with pytest.raises(KeyError):
        s.get("missing")
    with pytest.raises(B.SecretLocked):
        s.get("api.key")
    s.set("api.key", CANARY)
    with pytest.raises(B.SecretLocked):
        s.set("api.key", CANARY)
    store = run.calls[3]
    assert store["input"] == CANARY and all(CANARY not in a for a in store["argv"])


def test_bitwarden_backend_fails_closed_unless_unlocked() -> None:
    env = {"BW_SESSION": "session-" + "token"}
    unlocked = _done(0, json.dumps({"status": "unlocked"}))
    locked = _done(0, json.dumps({"status": "locked"}))
    run = FakeRun(
        unlocked, _done(0, CANARY), locked, unlocked, _done(1, "", "Not found."),
        unlocked, _done(1, "", "boom"), _done(1), _done(0, "not json"),
    )  # fmt: skip
    bw = B.BitwardenBackend(run, environ=env)
    assert bw.get("api.key") == CANARY
    assert run.calls[1]["env"] == {"BW_SESSION": env["BW_SESSION"]}
    with pytest.raises(B.SecretLocked, match="locked"):
        bw.get("api.key")
    with pytest.raises(KeyError):
        bw.get("missing")
    with pytest.raises(B.SecretLocked, match="exit 1"):
        bw.get("api.key")
    assert bw.status() == "error"
    assert bw.status() == "error"
    assert B.BitwardenBackend(FakeRun(), environ={})._env() == {}


@pytest.mark.parametrize("name", ["", "UPPER", "-flag", ".hidden", "a b", "x" * 65, "ünï"])
def test_bad_names_are_rejected_before_any_spawn(name: str) -> None:
    run = FakeRun()
    for backend in (B.KeychainBackend(run), B.SecretToolBackend(run), B.BitwardenBackend(run, environ={}),
                    B.EnvBackend({}), B.WinCredBackend()):  # fmt: skip
        with pytest.raises(SwitchyardError, match="invalid secret name"):
            backend.get(name)
    assert run.calls == []


def test_build_and_defaults() -> None:
    run = FakeRun()
    names = ["wincred", "keychain", "secret-tool", "bw"]
    assert [b.name for b in B.build(names, run, session_env="BW_SESSION", allow_env=False)] == names
    with pytest.raises(SwitchyardError, match="development"):
        B.build(["env"], run, session_env="X", allow_env=False)
    with pytest.raises(SwitchyardError, match="unknown"):
        B.build(["nope"], run, session_env="X", allow_env=False)
    assert B.default_order() in (["wincred"], ["keychain"], ["secret-tool"])
    assert B.EnvBackend({B.EnvBackend.variable("a.b-c"): "v"}).get("a.b-c") == "v"
    assert B.EnvBackend.variable("a.b-c") == "SWITCHYARD_SECRET_A_B_C"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager")
def test_wincred_round_trip_on_windows() -> None:
    w = B.WinCredBackend()
    name = "switchyard-test." + uuid.uuid4().hex[:12]
    value = "canary-" + uuid.uuid4().hex
    assert w.available()
    with pytest.raises(KeyError):
        w.get(name)
    try:
        w.set(name, value)
        assert w.get(name) == value
    finally:
        w.delete(name)
    with pytest.raises(KeyError):
        w.get(name)


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows path")
def test_wincred_is_locked_off_windows() -> None:
    w = B.WinCredBackend()
    assert not w.available()
    with pytest.raises(B.SecretLocked):
        w.get("api.key")
