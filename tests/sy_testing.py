"""Shared helpers for core tests (importable: `tests` is on pythonpath)."""

from __future__ import annotations

import json
import textwrap
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
        programs: list[str] | None = None,
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
        programs_line = f"programs = {json.dumps(programs)}\n" if programs is not None else ""
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
{programs_line}[contributes]
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


GOOD = """
class Mod:
    def __init__(self):
        self.ctx = None
    def activate(self, ctx):
        self.ctx = ctx
        ctx.log("{id}", "activated")
    def deactivate(self):
        self.ctx = None
    def health(self):
        return (self.ctx is not None, "ok")
"""


def write_module(
    root: Path,
    module_id: str,
    code: str = GOOD,
    *,
    request: tuple[str, ...] = (),
    activation: str = "manual",
    idle: int = 0,
    isolation: str = "in-process",
    entry: str = "mod:Mod",
    extra_files: dict[str, str] | None = None,
) -> Path:
    d = root / module_id
    d.mkdir(parents=True)
    module_file = entry.split(":")[0].replace(".", "/")
    target = d / f"{module_file}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(code).replace("{id}", module_id), encoding="utf-8")
    for name, text in (extra_files or {}).items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(textwrap.dedent(text), encoding="utf-8")
    idle_line = f"idle_stop_seconds = {idle}\n" if idle else ""
    (d / "module.toml").write_text(
        f"""schema = 1
[module]
id = "{module_id}"
name = "{module_id}"
version = "0.1.0"
license = "Apache-2.0"
license_class = "open"
summary = "test"
requires_core = ">=0.1,<1"
isolation = "{isolation}"
entry = "{entry}"
[capabilities]
request = {json.dumps(list(request))}
[contributes]
panels = ["{module_id}.status"]
log_streams = ["{module_id}"]
[lifecycle]
activation = "{activation}"
{idle_line}""",
        encoding="utf-8",
    )
    return d
