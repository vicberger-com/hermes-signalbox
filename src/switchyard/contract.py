"""Module contract suite: run one module directory through a real, throw-away core.

Every module (bundled or third-party) must pass ``run_contract(module_dir)`` before it ships. It needs only
the standard library, so third-party module repositories can call it from their own tests::

    from switchyard.contract import run_contract
    report = run_contract(Path(__file__).parent.parent)
    assert report.ok, report.summary()

Checks, in order (once one fails, later ones are skipped, except the denial and audit checks):

1. ``manifest``: the manifest loads and passes schema and cross-field checks.
2. ``discover``: the core discovers and verifies it (in-process modules are trusted for the run).
3. ``deny_ungranted``: before any grant, a request for a capability the module did not ask for
   (``net.outbound``, or ``process.spawn`` if it asks for that) raises ``CapabilityDenied`` and is audited.
4. ``activate``: with every requested capability granted, the module activates; activating again is a no-op.
5. ``health``: ``health()`` reports ok.
6. ``panels``: exactly the declared panels are registered, and each renders JSON-serialisable data.
7. ``deactivate``: deactivation (twice) stops it and removes its panels.
8. ``remove``: removal forgets the module and its grants.
9. ``audit``: the audit chain verifies and records the grant, activation, denial and removal.

The run happens in a temporary data directory that is deleted afterwards; nothing touches the caller's state.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from switchyard.capabilities import CORE_ACTOR
from switchyard.errors import CapabilityDenied, ManifestError
from switchyard.lifecycle import ModuleStatus
from switchyard.manifest import Manifest, load_manifest

ACTOR = "contract"
_SETTING_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _toml_table(name: str, values: Mapping[str, Any]) -> str:
    """Minimal TOML writer for flat settings (str, int, bool, lists of those); JSON literals fit TOML."""
    lines = [f"[{name}]"]
    for key, value in values.items():
        if not isinstance(key, str) or not _SETTING_KEY.match(key):
            raise ValueError(f"setting key {key!r} must match [a-z][a-z0-9_]*")
        items = value if isinstance(value, list) else [value]
        if not all(isinstance(v, (str, int, bool)) for v in items):
            raise ValueError(f"setting {key!r}: only str, int, bool and lists of those are supported")
        lines.append(f"{key} = {json.dumps(value, ensure_ascii=True)}")
    return "\n".join(lines) + "\n"


class ContractFailure(Exception):
    """A contract check did not hold. (Not ``assert``: checks must still run under ``python -O``.)"""


def _expect(condition: object, message: str) -> None:
    if not condition:
        raise ContractFailure(message)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ContractReport:
    module_id: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def summary(self) -> str:
        lines = [f"contract for {self.module_id or '<unknown>'}: {'PASS' if self.ok else 'FAIL'}"]
        lines += [
            f"  [{'ok' if c.ok else 'FAIL'}] {c.name}{': ' + c.detail if c.detail else ''}"
            for c in self.checks
        ]
        return "\n".join(lines)


def run_contract(
    module_dir: Path, *, settings: Mapping[str, Any] | None = None, bundled: bool = False
) -> ContractReport:
    """Run the contract. ``settings`` become the module's ``[modules.<id>]`` table for the run.

    ``bundled=True`` says the module ships inside this repository's ``switchyard/modules`` (or is the
    template for one). Without it, the production trust rule applies (H1 A-4): an ``in-process`` module
    outside the bundled modules fails the ``trust`` check, because a default install would not load it."""
    from switchyard.core import BUILTIN_MODULES

    module_dir = Path(module_dir).resolve()
    try:
        manifest = load_manifest(module_dir)
    except ManifestError as exc:
        return ContractReport("", [Check("manifest", False, "; ".join(exc.errors)[:500])])
    report = ContractReport(manifest.id, [Check("manifest", True)])
    if manifest.isolation == "in-process" and not (bundled or module_dir.is_relative_to(BUILTIN_MODULES)):
        why = "an in-process module loads only from the bundled modules; declare isolation = 'subprocess'"
        report.checks.append(Check("trust", False, why + " (or pass bundled=True for this repository)"))
        return report
    report.checks.append(Check("trust", True, manifest.isolation))
    with tempfile.TemporaryDirectory(prefix="switchyard-contract-") as tmp:
        _run(manifest, module_dir, Path(tmp), report, dict(settings or {}))
    return report


def _run(
    manifest: Manifest, module_dir: Path, tmp: Path, report: ContractReport, settings: dict[str, Any]
) -> None:
    from switchyard.core import Core  # local import: core pulls in every subsystem

    root = tmp / "modules"
    root.mkdir()
    shutil.copytree(module_dir, root / manifest.id, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    mid = manifest.id
    data = tmp / "data"
    data.mkdir()
    if settings:
        (data / "config.toml").write_text(_toml_table(f"modules.{mid}", settings), encoding="utf-8")

    def check(name: str, fn: Callable[[], str]) -> bool:
        try:
            detail = fn()
        except Exception as exc:  # a failing module must produce a report, not a crash
            message = str(exc) if isinstance(exc, ContractFailure) else type(exc).__name__ + ": " + str(exc)
            report.checks.append(Check(name, False, message[:500]))
            return False
        report.checks.append(Check(name, True, detail))
        return True

    with Core(data_dir=data, trusted_roots=[root], module_roots=[root], hosting=True) as core:

        def discover() -> str:
            _expect(core.manager.ids() == [mid], f"discovered {core.manager.ids()}")
            info = core.manager.info(mid)
            _expect(info.status is ModuleStatus.VERIFIED, f"status {info.status.value}: {info.error}")
            return ""

        def deny() -> str:
            probe = "process.spawn" if "net.outbound" in manifest.requested else "net.outbound"
            if probe in manifest.requested:
                return "module requests every probe capability; skipped"
            try:
                core.policy.require(mid, probe)
            except CapabilityDenied:
                return probe
            raise ContractFailure(f"{probe} was not denied")

        def activate() -> str:
            for capability in sorted(manifest.requested):
                core.run("module", "grant", {"id": mid, "capability": capability}, actor=ACTOR)
            core.run("module", "activate", {"id": mid}, actor=ACTOR)
            info = core.manager.info(mid)
            _expect(info.status is ModuleStatus.ACTIVE, f"status {info.status.value}: {info.error}")
            core.run("module", "activate", {"id": mid}, actor=ACTOR)
            _expect(
                core.manager.info(mid).status is ModuleStatus.ACTIVE, "second activate changed the status"
            )
            return ""

        def health() -> str:
            result = core.run("module", "health", {"id": mid}, actor=ACTOR)
            _expect(result["ok"] is True, f"health reported {result}")
            return str(result["detail"])

        def panels() -> str:
            declared = sorted(manifest.contributes["panels"])
            registered = sorted(core.panels.panels(mid))
            _expect(registered == declared, f"registered {registered}, declared {declared}")
            for panel in declared:
                data = core.run("module", "panel", {"id": mid, "panel": panel}, actor=ACTOR)
                json.dumps(data)
            return ", ".join(declared)

        def deactivate() -> str:
            core.run("module", "deactivate", {"id": mid}, actor=ACTOR)
            core.run("module", "deactivate", {"id": mid}, actor=ACTOR)
            _expect(core.manager.info(mid).status is not ModuleStatus.ACTIVE, "still active")
            _expect(core.panels.panels(mid) == [], "panels left registered")
            return ""

        def remove() -> str:
            core.run("module", "remove", {"id": mid}, actor=ACTOR)
            _expect(mid not in core.manager.ids(), "module still listed")
            _expect(not core.policy.stored_grants(mid), "grants kept in the store")  # H1 A-21
            return ""

        ok = check("discover", discover)
        denied = ok and check("deny_ungranted", deny) and "skipped" not in report.checks[-1].detail
        for name, fn in (
            ("activate", activate),
            ("health", health),
            ("panels", panels),
            ("deactivate", deactivate),
            ("remove", remove),
        ):
            ok = ok and check(name, fn)

        def audit() -> str:
            result = core.verify_audit()
            _expect(result.ok, f"audit chain broken: {result.reason}")
            actions = {r["action"] for r in core.run("audit", "tail", {"n": 500}, actor=CORE_ACTOR)}
            wanted = {"policy.denied"} if denied else set()
            if ok:
                wanted |= {"module.activated", "module.deactivated", "module.removed"}
                if manifest.requested:
                    wanted.add("policy.granted")
            missing = sorted(wanted - actions)
            _expect(not missing, f"audit records missing: {missing}")
            return f"{result.records} records"

        check("audit", audit)
