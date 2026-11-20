"""Module lifecycle, T1 in-process (spec section 3, Lifecycle)."""

from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from sy_testing import GOOD, RecordingAudit, write_module

from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.context import MemoryPanelRegistry
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.events import Event, EventBus
from switchyard.lifecycle import ModuleManager, ModuleStatus
from switchyard.logs import JsonlLogSink
from switchyard.scheduler import Scheduler, Trigger
from switchyard.state import StateStore

ROOT = Path(__file__).resolve().parents[2]


class Env:
    def __init__(self, tmp_path: Path, audit: RecordingAudit, *, store: StateStore | None = None) -> None:
        self.now = 1000.0
        self.audit = audit
        self.trusted = tmp_path / "trusted"
        self.untrusted = tmp_path / "untrusted"
        self.trusted.mkdir(exist_ok=True)
        self.untrusted.mkdir(exist_ok=True)
        self.events: list[Event] = []
        self.policy = PolicyEngine(MemoryGrantStore(), audit)
        self.bus = EventBus(audit, clock=lambda: "t")
        self.bus.subscribe("watch", "module.*", self.events.append)
        self.panels = MemoryPanelRegistry()
        self.logs = JsonlLogSink(tmp_path / "logs")
        self.scheduler = Scheduler(self.bus, audit, monotonic=lambda: self.now)
        self.store = store
        self.manager = ModuleManager(
            policy=self.policy, audit=audit, bus=self.bus, logs=self.logs, panels=self.panels,
            scheduler=self.scheduler, store=store, trusted_roots=[self.trusted], clock=lambda: self.now,
        )  # fmt: skip

    def event_types(self) -> list[str]:
        return [e.type for e in self.events]


@pytest.fixture
def env(tmp_path: Path, audit: RecordingAudit) -> Env:
    return Env(tmp_path, audit)


# discovery ------------------------------------------------------------------------------------------------


def test_discover_accepts_valid_and_rejects_invalid(env: Env) -> None:
    write_module(env.trusted, "alpha")
    bad = write_module(env.trusted, "beta")
    (bad / "module.toml").write_text("schema = 2", encoding="utf-8")
    found = env.manager.discover([env.trusted])
    assert found == ["alpha"]
    assert env.manager.info("alpha").state is ModuleStatus.VERIFIED
    assert "module.rejected" in env.audit.actions()
    assert env.event_types() == ["module.verified", "module.rejected"]


def test_duplicate_ids_are_rejected(env: Env, tmp_path: Path) -> None:
    write_module(env.trusted, "alpha")
    other = tmp_path / "elsewhere"
    write_module(other, "alpha", isolation="subprocess")
    env.manager.discover([env.trusted, other])
    rejected = [r for r in env.audit.records if r["action"] == "module.rejected"]
    assert rejected and "duplicate" in rejected[-1]["detail"]["reason"]


def test_untrusted_in_process_module_is_rejected(env: Env) -> None:
    write_module(env.untrusted, "alpha")
    assert env.manager.discover([env.untrusted]) == []
    assert "subprocess" in env.audit.records[-1]["detail"]["reason"]


def test_untrusted_subprocess_module_runs_in_the_t2_host(env: Env) -> None:
    write_module(env.untrusted, "alpha", isolation="subprocess")
    assert env.manager.discover([env.untrusted]) == ["alpha"]
    env.manager.activate("alpha", actor="user")
    assert env.manager.info("alpha").status is ModuleStatus.ACTIVE
    assert '"event":"activated"' in (env.logs.directory / "alpha.jsonl").read_text(encoding="utf-8")
    env.manager.deactivate("alpha", actor="user")


def test_trusted_root_check_resolves_symlinks_and_dotdot(env: Env) -> None:
    write_module(env.untrusted, "alpha")
    sneaky = env.trusted / ".." / "untrusted"
    assert env.manager.discover([sneaky]) == []


# activation -----------------------------------------------------------------------------------------------


def test_activate_and_deactivate(env: Env) -> None:
    write_module(env.trusted, "alpha")
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    assert env.manager.info("alpha").state is ModuleStatus.ACTIVE
    assert env.manager.health("alpha") == (True, "ok")
    env.manager.deactivate("alpha", actor="user")
    assert env.manager.info("alpha").state is ModuleStatus.STOPPED
    assert env.event_types()[-2:] == ["module.activated", "module.deactivated"]
    log = (env.logs.directory / "alpha.jsonl").read_text(encoding="utf-8")
    assert '"event":"activated"' in log
    env.manager.deactivate("alpha", actor="user")  # idempotent


def test_template_module_end_to_end(env: Env) -> None:
    shutil.copytree(ROOT / "templates" / "module", env.trusted / "example",
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))  # fmt: skip
    env.manager.discover([env.trusted])
    env.policy.grant("example", "ui.panel", actor="user")
    env.manager.activate("example", actor="user")
    assert env.panels.render("example", "example.status") == {"title": "Example", "state": "active"}
    env.manager.deactivate("example", actor="user")
    assert env.panels.panels("example") == []


def test_ungranted_capability_fails_the_module_closed(env: Env) -> None:
    shutil.copytree(ROOT / "templates" / "module", env.trusted / "example",
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))  # fmt: skip
    env.manager.discover([env.trusted])
    # H1 A-5: a required capability that is not granted stops activation before any module code runs
    with pytest.raises(CapabilityDenied, match=r"ui.panel"):
        env.manager.activate("example", actor="user")
    info = env.manager.info("example")
    assert info.state is ModuleStatus.VERIFIED and info.error is None
    assert "policy.denied" in env.audit.actions() and "module.failed" not in env.audit.actions()
    assert env.panels.panels("example") == []


@pytest.mark.parametrize(
    ("code", "entry", "error"),
    [
        ("raise ImportError('boom')", "mod:Mod", "ImportError"),
        ("class Other: ...", "mod:Mod", "AttributeError"),
        ("class Mod:\n    def activate(self, ctx): ...", "mod:Mod", "TypeError"),
        ("class Mod:\n    def __init__(self):\n        raise RuntimeError('x')\n"
         "    def activate(self, c): ...\n    def deactivate(self): ...\n    def health(self): ...",
         "mod:Mod", "RuntimeError"),
        ("class Mod:\n    def activate(self, c):\n        raise ValueError('sk-secret')\n"
         "    def deactivate(self): ...\n    def health(self): ...", "mod:Mod", "ValueError"),
    ],
    ids=["import-error", "missing-class", "missing-methods", "init-raises", "activate-raises"],
)  # fmt: skip
def test_broken_modules_fail_closed(env: Env, code: str, entry: str, error: str) -> None:
    write_module(env.trusted, "alpha", code, entry=entry)
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    info = env.manager.info("alpha")
    assert info.state is ModuleStatus.FAILED and info.error == error
    failed = [r for r in env.audit.records if r["action"] == "module.failed"][-1]
    assert failed["detail"]["error"] == error
    assert "sk-secret" not in json.dumps(env.audit.records)


def test_failed_module_can_be_retried_after_a_fix(env: Env) -> None:
    d = write_module(env.trusted, "alpha", "raise ImportError('boom')")
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    assert env.manager.info("alpha").state is ModuleStatus.FAILED
    (d / "mod.py").write_text(textwrap.dedent(GOOD).replace("{id}", "alpha"), encoding="utf-8")
    env.manager.activate("alpha", actor="user")
    assert env.manager.info("alpha").state is ModuleStatus.ACTIVE


def test_disabled_module_cannot_be_activated(env: Env) -> None:
    write_module(env.trusted, "alpha")
    env.manager.discover([env.trusted])
    env.manager.set_mode("alpha", "disabled", actor="user")
    with pytest.raises(SwitchyardError, match="disabled"):
        env.manager.activate("alpha", actor="user")


def test_disabling_an_active_module_stops_it(env: Env) -> None:
    write_module(env.trusted, "alpha")
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    env.manager.set_mode("alpha", "disabled", actor="user")
    assert env.manager.info("alpha").state is ModuleStatus.STOPPED
    with pytest.raises(SwitchyardError, match="mode"):
        env.manager.set_mode("alpha", "sometimes", actor="user")


def test_deactivate_failure_still_stops_and_cleans_up(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.subscribe("x.y", lambda e: None)
        def deactivate(self):
            raise RuntimeError("cleanup failed")
        def health(self):
            return True
    """
    write_module(env.trusted, "alpha", code)
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    env.scheduler.add(
        Trigger(id="alpha.t", owner="alpha", kind="time", spec={"every": 5}, callback=lambda p: None)
    )
    assert env.bus.subscriptions("alpha") == 1
    env.manager.deactivate("alpha", actor="user")
    assert env.manager.info("alpha").state is ModuleStatus.STOPPED
    assert env.bus.subscriptions("alpha") == 0 and env.scheduler.ids() == []
    assert "module.deactivate_failed" in env.audit.actions()


def test_health_exception_fails_closed(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx): ...
        def deactivate(self): ...
        def health(self):
            raise RuntimeError("bad")
    """
    write_module(env.trusted, "alpha", code)
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    assert env.manager.health("alpha") == (False, "health check raised RuntimeError")
    assert env.manager.info("alpha").state is ModuleStatus.FAILED


@pytest.mark.parametrize(
    ("result", "expected"),
    [(True, (True, "")), ((False, "warming"), (False, "warming")), ("odd", (False, "invalid health result"))],
)
def test_health_result_shapes(env: Env, result: Any, expected: tuple[bool, str]) -> None:
    code = f"""
    class Mod:
        def activate(self, ctx): ...
        def deactivate(self): ...
        def health(self):
            return {result!r}
    """
    write_module(env.trusted, "alpha", code)
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    assert env.manager.health("alpha") == expected


def test_health_of_stopped_module(env: Env) -> None:
    write_module(env.trusted, "alpha")
    env.manager.discover([env.trusted])
    assert env.manager.health("alpha") == (False, "verified")


def test_health_object_with_ok_and_detail(env: Env) -> None:
    shutil.copytree(ROOT / "templates" / "module", env.trusted / "example",
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))  # fmt: skip
    env.manager.discover([env.trusted])
    env.policy.grant("example", "ui.panel", actor="user")
    env.manager.activate("example", actor="user")
    assert env.manager.health("example") == (True, "active")


def test_bus_handler_failure_fails_the_module(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.subscribe("x.y", self.on)
        def on(self, event):
            raise RuntimeError("handler")
        def deactivate(self): ...
        def health(self):
            return True
    """
    write_module(env.trusted, "alpha", code)
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    env.bus.publish("core", "x.y", {})
    assert env.manager.info("alpha").state is ModuleStatus.FAILED


# modules are separate packages ---------------------------------------------------------------------------


def test_same_file_names_do_not_clash_and_relative_imports_work(env: Env) -> None:
    pkg = """
    from .helper import NAME
    class Mod:
        def activate(self, ctx):
            ctx.log("{id}", NAME)
        def deactivate(self): ...
        def health(self):
            return True
    """
    write_module(env.trusted, "alpha", pkg, entry="pkg:Mod",
                 extra_files={"pkg/helper.py": "NAME = 'from-alpha'\n"})  # fmt: skip
    write_module(env.trusted, "beta", pkg, entry="pkg:Mod",
                 extra_files={"pkg/helper.py": "NAME = 'from-beta'\n"})  # fmt: skip
    (env.trusted / "alpha" / "pkg.py").rename(env.trusted / "alpha" / "pkg" / "__init__.py")
    (env.trusted / "beta" / "pkg.py").rename(env.trusted / "beta" / "pkg" / "__init__.py")
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    env.manager.activate("beta", actor="user")
    a = (env.logs.directory / "alpha.jsonl").read_text(encoding="utf-8")
    b = (env.logs.directory / "beta.jsonl").read_text(encoding="utf-8")
    assert "from-alpha" in a and "from-beta" in b


# idle stop and auto mode ---------------------------------------------------------------------------------


def test_auto_modules_start_and_idle_stop(env: Env) -> None:
    write_module(env.trusted, "auto1", activation="auto", idle=60)
    write_module(env.trusted, "manual1")
    env.manager.discover([env.trusted])
    env.manager.start_auto(actor="core")
    assert env.manager.info("auto1").state is ModuleStatus.ACTIVE
    assert env.manager.info("manual1").state is ModuleStatus.VERIFIED
    env.now += 59
    env.manager.tick()
    env.manager.touch("auto1")
    env.now += 59
    env.manager.tick()
    assert env.manager.info("auto1").state is ModuleStatus.ACTIVE
    env.now += 1
    env.manager.tick()
    assert env.manager.info("auto1").state is ModuleStatus.STOPPED
    stop = [r for r in env.audit.records if r["action"] == "module.deactivated"][-1]
    assert stop["detail"] == {"reason": "idle"}


# removal and persistence ---------------------------------------------------------------------------------


def test_remove_drops_grants_data_and_imports(tmp_path: Path, audit: RecordingAudit) -> None:
    store = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backup")
    store.migrate()
    env = Env(tmp_path, audit, store=store)
    write_module(env.trusted, "alpha", request=("schedule",))
    env.manager.discover([env.trusted])
    env.policy.grant("alpha", "schedule", actor="user")
    env.manager.activate("alpha", actor="user")
    store.module("alpha").kv_set("k", 1)
    env.manager.remove("alpha", actor="user")
    assert "alpha" not in env.manager.ids()
    assert store.module("alpha").kv_get("k") is None
    assert not any(name.startswith("_switchyard_modules.alpha") for name in sys.modules)
    assert store.core_query("SELECT count(*) FROM modules WHERE id = 'alpha'") == [(0,)]
    assert env.event_types()[-1] == "module.removed"
    with pytest.raises(SwitchyardError, match="unknown module"):
        env.manager.info("alpha")
    store.close()


def test_remove_keep_data(tmp_path: Path, audit: RecordingAudit) -> None:
    store = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backup")
    store.migrate()
    env = Env(tmp_path, audit, store=store)
    write_module(env.trusted, "alpha", request=("schedule",))
    env.manager.discover([env.trusted])
    env.policy.grant("alpha", "schedule", actor="user")
    store.module("alpha").kv_set("k", 1)
    env.manager.remove("alpha", actor="user", keep_data=True)
    assert store.module("alpha").kv_get("k") == 1
    assert (
        store.core_query("SELECT capability FROM grants WHERE module_id = 'alpha'") == []
    )  # memory store used
    store.close()


def test_mode_persists_across_managers(tmp_path: Path, audit: RecordingAudit) -> None:
    store = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backup")
    store.migrate()
    env = Env(tmp_path, audit, store=store)
    write_module(env.trusted, "alpha")
    env.manager.discover([env.trusted])
    env.manager.set_mode("alpha", "disabled", actor="user")
    env2 = Env(tmp_path, audit, store=store)
    env2.manager.discover([env2.trusted])
    assert env2.manager.info("alpha").mode == "disabled"
    store.close()


def test_context_exposes_module_state(tmp_path: Path, audit: RecordingAudit) -> None:
    store = StateStore(tmp_path / "state.db", backup_dir=tmp_path / "backup")
    store.migrate()
    env = Env(tmp_path, audit, store=store)
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.state.kv_set("seen", True)
        def deactivate(self): ...
        def health(self):
            return True
    """
    write_module(env.trusted, "alpha", code)
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    assert store.module("alpha").kv_get("seen") is True
    store.close()


def test_list_reports_every_module(env: Env) -> None:
    write_module(env.trusted, "alpha")
    write_module(env.trusted, "beta", activation="auto")
    env.manager.discover([env.trusted])
    rows = {i.id: i for i in env.manager.modules()}
    assert set(rows) == {"alpha", "beta"} and rows["beta"].mode == "auto"
    assert rows["alpha"].version == "0.1.0" and rows["alpha"].isolation == "in-process"


def test_rediscovery_edge_cases(env: Env, tmp_path: Path) -> None:
    assert env.manager.discover([tmp_path / "missing"]) == []
    d = write_module(env.trusted, "alpha")
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    env.manager.activate("alpha", actor="user")  # already active: no second activation
    assert env.event_types().count("module.activated") == 1
    assert env.manager.discover([env.trusted]) == ["alpha"]  # running module keeps its manifest
    env.manager.deactivate("alpha", actor="user")
    text = (d / "module.toml").read_text(encoding="utf-8")
    (d / "module.toml").write_text(text.replace("[contributes]", '[contributes]\npolicies = ["allow:x"]'),
                                   encoding="utf-8")  # fmt: skip
    assert env.manager.discover([env.trusted]) == []
    assert "unsupported policy" in env.audit.records[-1]["detail"]["reason"]


def test_failure_while_active_runs_module_cleanup(env: Env) -> None:
    code = """
    class Mod:
        def activate(self, ctx):
            ctx.subscribe("x.y", self.on)
        def on(self, event):
            raise RuntimeError("handler")
        def deactivate(self):
            raise OSError("cleanup also fails")
        def health(self):
            return True
    """
    write_module(env.trusted, "alpha", code)
    env.manager.discover([env.trusted])
    env.manager.activate("alpha", actor="user")
    env.bus.publish("core", "x.y", {})
    env.bus.publish("core", "x.y", {})  # unsubscribed after the first failure
    assert env.manager.info("alpha").error == "RuntimeError"
    assert env.audit.actions().count("module.failed") == 1
    cleanup = [r for r in env.audit.records if r["action"] == "module.deactivate_failed"]
    assert cleanup[-1]["detail"] == {"error": "OSError"}
