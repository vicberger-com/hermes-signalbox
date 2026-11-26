"""Capabilities, grants and the policy engine (spec section 3, Policy).

Default deny. A capability is effective for a module only when all of these hold:

1. it is in the core vocabulary (``CAPABILITIES``, identical to the manifest schema enum);
2. the module's manifest requests it;
3. the module's own ``contributes.policies`` do not deny it (policies can only tighten);
4. a grant is stored for it.

Every grant, revoke, refused grant and denied check is written to the audit sink. Allowed checks are not
audited (they are frequent and carry no decision). The engine is the single choke point: brokers call
``require``, ``require_host`` or ``require_secret`` before acting.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from hermes_signalbox.errors import CapabilityDenied, ManifestError, UsageError
from hermes_signalbox.manifest import Manifest

CAPABILITIES: frozenset[str] = frozenset({
    "fs.read", "fs.write", "net.outbound", "secrets.read", "process.spawn",
    "hermes.hooks", "hermes.tools", "hermes.config.write", "hermes.delegation", "hermes.output",
    "llm.free", "llm.paid", "ui.panel", "schedule", "notify", "core.read",
})  # fmt: skip

CORE_ACTOR = "core"


class AuditSink(Protocol):
    """Where policy decisions go. ``AuditLog`` implements it; ``detail`` holds names, never values."""

    def append(self, *, actor: str, action: str, module: str, detail: Mapping[str, str]) -> object: ...


class GrantStore(Protocol):
    """Persistence for grants. The SQLite state store implements this; ``MemoryGrantStore`` is for tests."""

    def load(self, module_id: str) -> frozenset[str]: ...

    def add(self, module_id: str, capability: str) -> None: ...

    def remove(self, module_id: str, capability: str) -> None: ...

    def remove_all(self, module_id: str) -> None: ...


class MemoryGrantStore:
    """In-memory ``GrantStore``."""

    def __init__(self) -> None:
        self._grants: dict[str, set[str]] = {}

    def load(self, module_id: str) -> frozenset[str]:
        return frozenset(self._grants.get(module_id, ()))

    def add(self, module_id: str, capability: str) -> None:
        self._grants.setdefault(module_id, set()).add(capability)

    def remove(self, module_id: str, capability: str) -> None:
        self._grants.get(module_id, set()).discard(capability)

    def remove_all(self, module_id: str) -> None:
        self._grants.pop(module_id, None)


_WINDOWS_EXTENSIONS = (".exe", ".com", ".cmd", ".bat")


def program_key(name: str) -> str:
    """How program names compare: exact on POSIX; on Windows case-insensitive, without .exe/.com/.cmd/.bat."""
    if os.name != "nt":
        return name
    low = name.lower()
    for ext in _WINDOWS_EXTENSIONS:
        if low.endswith(ext):
            return low[: -len(ext)]
    return low


@dataclass(frozen=True)
class _Registration:
    requested: frozenset[str]
    denied: frozenset[str]
    net_hosts: frozenset[str]
    secrets: frozenset[str]
    programs: frozenset[str] | None = None  # None: no list, any program (H1 B-10); empty: none (S1-4)


def parse_policies(manifest: Manifest) -> frozenset[str]:
    """Parse ``contributes.policies``. M0 grammar: ``deny:<capability>``; anything else is an error."""
    denied: set[str] = set()
    errors: list[str] = []
    for rule in manifest.contributes["policies"]:
        verb, _, cap = rule.partition(":")
        if verb != "deny" or cap not in CAPABILITIES:
            errors.append(f"unsupported policy {rule!r} (M0 accepts 'deny:<capability>')")
        else:
            denied.add(cap)
    if errors:
        raise ManifestError(manifest.path, errors)
    return frozenset(denied)


_CLIP = 1000  # below the audit log's 1024-character detail limit, with room for the marker


def _clip(detail: Mapping[str, str]) -> dict[str, str]:
    return {
        str(k)[:100]: (v if len(v) <= _CLIP else f"{v[: _CLIP - 20]}[+{len(v) - (_CLIP - 20)} chars]")
        for k, v in ((k, str(v)) for k, v in detail.items())
    }


class PolicyEngine:
    """Default-deny capability checks for registered modules. Thread-safe."""

    def __init__(self, store: GrantStore, audit: AuditSink) -> None:
        self._store = store
        self._audit = audit
        self._modules: dict[str, _Registration] = {}
        self._lock = threading.RLock()

    # registration -------------------------------------------------------------------------------------

    def register(self, manifest: Manifest) -> None:
        """Register or re-register a module from its (validated) manifest."""
        reg = _Registration(
            requested=manifest.requested & CAPABILITIES,
            denied=parse_policies(manifest),
            net_hosts=frozenset(h.lower() for h in manifest.net_hosts),
            secrets=frozenset(manifest.secrets),
            programs=None
            if manifest.programs is None
            else frozenset(program_key(p) for p in manifest.programs),
        )
        with self._lock:
            self._modules[manifest.id] = reg
            # H1 A-6: consent belongs to the capabilities this code asks for. A stored grant the manifest
            # no longer requests (or now denies) is removed; a later version asking again needs a new grant.
            for capability in sorted(self._store.load(manifest.id) - (reg.requested - reg.denied)):
                self._store.remove(manifest.id, capability)
                detail = {"capability": capability, "reason": "no longer requested"}
                self._audit.append(
                    actor=CORE_ACTOR, action="policy.revoked", module=manifest.id, detail=detail
                )

    def stored_grants(self, module_id: str) -> frozenset[str]:
        """Grants in the store, whether or not the module is registered (the contract checks removal)."""
        with self._lock:
            return frozenset(self._store.load(module_id))

    def unregister(self, module_id: str, *, actor: str, keep_grants: bool = False) -> None:
        with self._lock:
            self._modules.pop(module_id, None)
            if not keep_grants:
                self._store.remove_all(module_id)
                self._audit.append(actor=actor, action="policy.grants_removed", module=module_id, detail={})

    # grants -------------------------------------------------------------------------------------------

    def _refuse(self, module_id: str, capability: str, actor: str, reason: str) -> CapabilityDenied:
        self._audit_refusal(module_id, capability, actor, reason)
        return CapabilityDenied(f"cannot grant {capability[:100]!r} to {module_id!r}: {reason}")

    def _audit_refusal(self, module_id: str, capability: str, actor: str, reason: str) -> None:
        self._audit.append(
            actor=actor,
            action="policy.grant_refused",
            module=module_id,
            detail=_clip({"capability": capability, "reason": reason}),
        )

    def grant(self, module_id: str, capability: str, *, actor: str) -> None:
        with self._lock:
            reg = self._modules.get(module_id)
            if capability not in CAPABILITIES:
                raise self._refuse(module_id, capability, actor, "unknown capability")
            if reg is None:
                # H4 R1-F4: an unknown name is a usage error (exit 2), not a denial; still audited
                self._audit_refusal(module_id, capability, actor, "module not registered")
                raise UsageError(f"unknown module {module_id[:100]!r}")
            if capability not in reg.requested:
                raise self._refuse(module_id, capability, actor, "not requested in the manifest")
            if capability in reg.denied:
                raise self._refuse(module_id, capability, actor, "denied by the module policy")
            self._store.add(module_id, capability)
            self._audit.append(
                actor=actor, action="policy.granted", module=module_id, detail={"capability": capability}
            )

    def revoke(self, module_id: str, capability: str, *, actor: str) -> None:
        with self._lock:
            if capability not in self._store.load(module_id):
                return
            self._store.remove(module_id, capability)
            self._audit.append(
                actor=actor, action="policy.revoked", module=module_id, detail={"capability": capability}
            )

    def granted(self, module_id: str) -> frozenset[str]:
        """Effective capabilities: stored grants limited by the current manifest and the module policy."""
        with self._lock:
            reg = self._modules.get(module_id)
            if reg is None:
                return frozenset()
            return (self._store.load(module_id) & reg.requested) - reg.denied

    # checks -------------------------------------------------------------------------------------------

    def _deny(self, module_id: str, detail: dict[str, str], message: str) -> CapabilityDenied:
        # H1 A-2: a module controls these strings (hosts, panel ids). The denial is always recorded, with long
        # values shortened, and the caller always gets CapabilityDenied.
        self._audit.append(actor=CORE_ACTOR, action="policy.denied", module=module_id, detail=_clip(detail))
        return CapabilityDenied(message[:500])

    def require(self, module_id: str, capability: str, **detail: str) -> None:
        """Raise ``CapabilityDenied`` (and audit it) unless ``capability`` is effective for ``module_id``."""
        if capability not in self.granted(module_id):
            raise self._deny(
                module_id,
                {"capability": capability, **detail},
                f"module {module_id!r} does not hold capability {capability!r}",
            )

    def _registration(self, module_id: str, capability: str, missing: str, **detail: str) -> _Registration:
        """``capability`` for ``module_id``, then its registration (H1 A-30: the shared part of the allow-list
        checks). A module unregistered between the two steps is refused with ``missing`` (H1 A-15)."""
        self.require(module_id, capability, **detail)
        with self._lock:
            reg = self._modules.get(module_id)
        if reg is None:
            raise self._deny(module_id, {"capability": capability, **detail}, missing)
        return reg

    def require_host(self, module_id: str, host: str) -> None:
        """``net.outbound`` plus the manifest's host allow-list (case-insensitive, exact match)."""
        reg = self._registration(
            module_id, "net.outbound", f"module {module_id!r} is not registered", host=host
        )
        host = host.lower()
        bare = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        if host not in reg.net_hosts and bare not in reg.net_hosts:  # a bare entry allows any port
            raise self._deny(
                module_id,
                {"capability": "net.outbound", "host": host},
                f"module {module_id!r} may not contact {host!r}",
            )

    def require_program(self, module_id: str, argv0: str) -> None:
        """``process.spawn`` plus the manifest's ``programs`` list when it has one (H1 B-10). With a list,
        ``argv[0]`` must be a bare name (found on PATH), so a module cannot run its own file named like a
        listed program. Without one, any program runs, as the grant prompt says."""
        program = os.path.basename(argv0.replace("\\", "/"))
        missing = f"module {module_id!r} is not registered"
        reg = self._registration(module_id, "process.spawn", missing, program=program)
        if reg.programs is None:
            return
        if (
            not argv0.isascii()
        ):  # 1.1 acceptance S1-5: case folding maps some non-ASCII letters onto ASCII ones
            raise self._deny(
                module_id,
                {"capability": "process.spawn", "program": program},
                f"module {module_id!r} must name a listed program in ASCII",
            )
        if program != argv0:
            raise self._deny(
                module_id,
                {"capability": "process.spawn", "program": program},
                f"module {module_id!r} must name a program by its bare program name, not a path",
            )
        if program_key(program) not in reg.programs:
            raise self._deny(
                module_id,
                {"capability": "process.spawn", "program": program},
                f"module {module_id!r} may not run {program!r}",
            )

    def require_secret(self, module_id: str, name: str) -> None:
        """``secrets.read`` plus the manifest's secret-name allow-list."""
        refused = f"module {module_id!r} may not read secret {name!r}"
        reg = self._registration(module_id, "secrets.read", refused, secret=name)
        if name not in reg.secrets:
            raise self._deny(module_id, {"capability": "secrets.read", "secret": name}, refused)
