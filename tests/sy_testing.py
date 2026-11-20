"""Shared helpers for core tests (importable: `tests` is on pythonpath)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from switchyard.manifest import Manifest, load_manifest

ManifestFactory = Callable[..., Manifest]


@pytest.fixture
def make_manifest(tmp_path: Path) -> ManifestFactory:
    """Write a minimal valid module and load it. Keyword arguments override manifest fields."""
    counter = iter(range(1000))

    def factory(
        module_id: str = "demo",
        *,
        request: list[str] | None = None,
        net_hosts: list[str] | None = None,
        secrets: list[str] | None = None,
        panels: list[str] | None = None,
        log_streams: list[str] | None = None,
        policies: list[str] | None = None,
    ) -> Manifest:
        d = tmp_path / f"{module_id}-{next(counter)}"
        d.mkdir()
        (d / "mod.py").write_text("class Mod: ...\n", encoding="utf-8")
        lists = {
            "request": request if request is not None else ["ui.panel"],
            "net_hosts": net_hosts or [],
            "secrets": secrets or [],
            "panels": panels if panels is not None else [f"{module_id}.status"],
            "log_streams": log_streams if log_streams is not None else [module_id],
            "policies": policies or [],
        }
        q = {k: json.dumps(v) for k, v in lists.items()}
        (d / "module.toml").write_text(
            f"""schema = 1
[module]
id = "{module_id}"
name = "Demo"
version = "0.1.0"
license = "Apache-2.0"
license_class = "open"
summary = "test module"
requires_core = ">=0.1,<1"
isolation = "in-process"
entry = "mod:Mod"
[capabilities]
request = {q["request"]}
net_hosts = {q["net_hosts"]}
secrets = {q["secrets"]}
[contributes]
panels = {q["panels"]}
log_streams = {q["log_streams"]}
policies = {q["policies"]}
[lifecycle]
activation = "manual"
""",
            encoding="utf-8",
        )
        return load_manifest(d)

    return factory


@dataclass
class RecordingAudit:
    """AuditSink test double: keeps every record in memory."""

    records: list[dict[str, Any]] = field(default_factory=list)

    def append(self, *, actor: str, action: str, module: str, detail: Mapping[str, str]) -> None:
        self.records.append({"actor": actor, "action": action, "module": module, "detail": dict(detail)})

    def actions(self) -> list[str]:
        return [r["action"] for r in self.records]


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit()
