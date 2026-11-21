"""1.1 backlog: duplication and cohesion (H1 A-30 #96). Behaviour is covered by the existing suites; these
tests pin the structure so the duplication does not come back."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from switchyard import capabilities, context, lifecycle
from switchyard.capabilities import MemoryGrantStore, PolicyEngine
from switchyard.errors import CapabilityDenied

SRC = Path(lifecycle.__file__).resolve().parent


def test_h1_a30_bridge_availability_is_checked_in_one_place() -> None:
    text = (SRC / "context.py").read_text(encoding="utf-8")
    assert text.count("bridge is not available") == 1
    assert text.count("is not declared in contributes.hooks") == 1


def test_h1_a30_hermes_registrations_share_one_helper() -> None:
    for name in ("hermes_hook", "hermes_gate", "hermes_transform", "hermes_delegation", "hermes_middleware"):
        assert "self._hermes_port(" in inspect.getsource(getattr(context.ModuleContext, name)), name


def test_h1_a30_allow_list_checks_share_one_lookup() -> None:
    for name in ("require_host", "require_program", "require_secret"):
        source = inspect.getsource(getattr(PolicyEngine, name))
        assert "self._registration(" in source and "self._lock" not in source, name


def test_h1_a30_an_unregistered_module_is_refused_by_every_allow_list_check() -> None:
    class _Audit:
        def append(self, **_k: object) -> None:
            return None

    engine = PolicyEngine(MemoryGrantStore(), _Audit())
    for call in (
        lambda: engine.require_host("ghost", "example.com"),
        lambda: engine.require_program("ghost", "git"),
        lambda: engine.require_secret("ghost", "token"),
    ):
        with pytest.raises(CapabilityDenied):
            call()


def test_h1_a30_discovery_lives_outside_the_manager_file() -> None:
    tree = ast.parse((SRC / "lifecycle.py").read_text(encoding="utf-8"))
    manager = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ModuleManager")
    methods = {n.name for n in manager.body if isinstance(n, ast.FunctionDef)}
    assert not methods & {"discover", "_discover_one", "_reject", "_is_trusted", "_verification_fingerprint"}
    assert hasattr(lifecycle.ModuleManager, "discover")  # still part of the manager's interface
    assert len((SRC / "lifecycle.py").read_text(encoding="utf-8").splitlines()) < 450


def test_h1_a30_capabilities_module_keeps_its_public_names() -> None:
    assert {"PolicyEngine", "CORE_ACTOR", "AuditSink"} <= set(vars(capabilities))
