"""1.1 backlog: the module-facing context is typed, so mypy can check module code (H1 A-29 #95)."""

from __future__ import annotations

import typing
from pathlib import Path

import pytest

from hermes_signalbox import context

SRC = Path(context.__file__).resolve().parent

FACADES = {
    "state": "ModuleState",
    "notify": "ModuleNotify",
    "secrets": "ModuleSecrets",
    "net": "ModuleNet",
    "schedule": "ModuleSchedule",
    "fs": "ModuleFs",
    "core": "CoreView",
    "hermes_config": "ModuleConfig",
    "spawn": "ModuleProcess",
}


def _return_hint(name: str) -> object:
    prop = getattr(context.ModuleContext, name)
    namespace = vars(context) | context._facade_types()
    return typing.get_type_hints(prop.fget, globalns=namespace)["return"]


@pytest.mark.parametrize(("prop", "cls"), sorted(FACADES.items()))
def test_h1_a29_each_facade_property_returns_its_class(prop: str, cls: str) -> None:
    hint = _return_hint(prop)
    assert hint is not object and getattr(hint, "__name__", "") == cls


def test_h1_a29_optional_services_are_typed_ports() -> None:
    hints = typing.get_type_hints(context.ContextServices, globalns=vars(context) | context._facade_types())
    assert hints["audit"] != typing.Any and hints["bridge"] != typing.Any
    assert "BridgePort" in str(hints["bridge"]) and "AuditSink" in str(hints["audit"])


def test_h1_a29_no_type_ignore_left_in_the_audit_reader() -> None:
    assert "type: ignore" not in (SRC / "audit.py").read_text(encoding="utf-8")
