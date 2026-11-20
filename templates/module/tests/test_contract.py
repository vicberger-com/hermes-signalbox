"""Contract tests every module ships. Copy with the module and extend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from example import ExampleModule


class FakeContext:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.panels: dict[str, Any] = {}

    def log(self, stream: str, event: str, **fields: Any) -> None:
        self.events.append((stream, event))

    def register_panel(self, panel_id: str, render: Any) -> None:
        self.panels[panel_id] = render


def test_lifecycle_is_idempotent_and_leaves_nothing_active() -> None:
    module, ctx = ExampleModule(), FakeContext()
    assert module.health().ok is False
    module.activate(ctx)
    module.activate(ctx)
    assert module.health().ok is True
    assert ctx.events == [("example", "activated")]
    module.deactivate()
    module.deactivate()
    assert module.health().ok is False
    assert ctx.events[-1] == ("example", "deactivated") and len(ctx.events) == 2


def test_contributed_panel_matches_manifest_and_returns_plain_data() -> None:
    module, ctx = ExampleModule(), FakeContext()
    module.activate(ctx)
    assert set(ctx.panels) == {"example.status"}
    data = ctx.panels["example.status"]()
    assert data == {"title": "Example", "state": "active"}


def test_full_contract_through_a_real_core() -> None:
    """The shared contract suite: manifest, discovery, denial, activation, health, panels, removal, audit."""
    from switchyard.contract import run_contract

    # bundled=True: an in-process module belongs in this repository's switchyard/modules. A module shipped
    # on its own declares isolation = "subprocess" and drops the flag (the contract then checks trust).
    report = run_contract(Path(__file__).resolve().parents[1], bundled=True)
    assert report.ok, report.summary()
