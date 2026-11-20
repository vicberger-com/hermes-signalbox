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

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from switchyard.errors import CapabilityDenied, ManifestError
from switchyard.manifest import Manifest

CAPABILITIES: frozenset[str] = frozenset({
    "fs.read", "fs.write", "net.outbound", "secrets.read", "process.spawn",
    "hermes.hooks", "hermes.tools", "hermes.config.write",
    "llm.free", "llm.paid", "ui.panel", "schedule", "notify",
})  # fmt: skip

CORE_ACTOR = "core"


class AuditSink(Protocol):
    """Where policy decisions go. ``AuditLog`` implements it; ``detail`` holds names, never values."""

    def append(self, *, actor: str, action: str, module: str, detail: Mapping[str, str]) -> None: ...


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


@dataclass(frozen=True)
class _Registration:
    requested: frozenset[str]
    denied: frozenset[str]
    net_hosts: frozenset[str]
    secrets: frozenset[str]


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
        )
        with self._lock:
            self._modules[manifest.id] = reg

    def unregister(self, module_id: str, *, actor: str, keep_grants: bool = False) -> None:
        with self._lock:
            self._modules.pop(module_id, None)
            if not keep_grants:
                self._store.remove_all(module_id)
                self._audit.append(actor=actor, action="policy.grants_removed", module=module_id, detail={})

    # grants -------------------------------------------------------------------------------------------

    def _refuse(self, module_id: str, capability: str, actor: str, reason: str) -> CapabilityDenied:
        self._audit.append(
            actor=actor,
            action="policy.grant_refused",
            module=module_id,
            detail={"capability": capability, "reason": reason},
        )
        return CapabilityDenied(f"cannot grant {capability!r} to {module_id!r}: {reason}")

    def grant(self, module_id: str, capability: str, *, actor: str) -> None:
        with self._lock:
            reg = self._modules.get(module_id)
            if capability not in CAPABILITIES:
                raise self._refuse(module_id, capability, actor, "unknown capability")
            if reg is None:
                raise self._refuse(module_id, capability, actor, "module not registered")
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
        self._audit.append(actor=CORE_ACTOR, action="policy.denied", module=module_id, detail=detail)
        return CapabilityDenied(message)

    def require(self, module_id: str, capability: str, **detail: str) -> None:
        """Raise ``CapabilityDenied`` (and audit it) unless ``capability`` is effective for ``module_id``."""
        if capability not in self.granted(module_id):
            raise self._deny(
                module_id,
                {"capability": capability, **detail},
                f"module {module_id!r} does not hold capability {capability!r}",
            )

    def require_host(self, module_id: str, host: str) -> None:
        """``net.outbound`` plus the manifest's host allow-list (case-insensitive, exact match)."""
        self.require(module_id, "net.outbound", host=host)
        with self._lock:
            reg = self._modules[module_id]
        if host.lower() not in reg.net_hosts:
            raise self._deny(
                module_id,
                {"capability": "net.outbound", "host": host},
                f"module {module_id!r} may not contact {host!r}",
            )

    def require_secret(self, module_id: str, name: str) -> None:
        """``secrets.read`` plus the manifest's secret-name allow-list."""
        self.require(module_id, "secrets.read", secret=name)
        with self._lock:
            reg = self._modules[module_id]
        if name not in reg.secrets:
            raise self._deny(
                module_id,
                {"capability": "secrets.read", "secret": name},
                f"module {module_id!r} may not read secret {name!r}",
            )
