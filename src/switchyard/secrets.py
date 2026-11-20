"""Secrets broker interface (spec section 3, Secrets broker; DESIGN.md section 4, control 2).

Modules handle ``secret://name`` references, never values. ``SecretsBroker.use(module, ref, fn)``:

1. checks ``secrets.read`` and the module's declared secret names (``PolicyEngine.require_secret``);
2. asks each backend in order; the first *available* backend that has the name wins; none -> fail closed;
3. registers the value with the ``Redactor`` (audit and log sinks redact through it); audits the use by name;
4. calls ``fn(value)`` and returns its result only if the value does not appear in it (``SecretLeak``);
5. if ``fn`` raises, re-raises with the exception class name only, because the message may hold the value.

Real backends (OS keyring, Vaultwarden) are module M1; the core ships only ``MemoryBackend`` for tests.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from switchyard.capabilities import AuditSink, PolicyEngine
from switchyard.errors import SwitchyardError

T = TypeVar("T")
REF_PREFIX = "secret://"
_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
MIN_REDACT_CHARS = 4
MASK = "[REDACTED]"

# Common credential shapes, redacted even when the value was never registered (defence in depth).
DEFAULT_PATTERNS: tuple[str, ...] = (
    r"sk-ant-[A-Za-z0-9_-]{16,}",
    r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"AKIA[0-9A-Z]{16}",
    r"xox[abposr]-[A-Za-z0-9-]{10,}",
    r"(?i)(?<=bearer )[A-Za-z0-9._~+/=-]{16,}",
)


class SecretUnavailable(SwitchyardError):
    """No available backend holds the secret (or the backend is locked). Fail closed."""


class SecretLeak(SwitchyardError):
    """A result would have carried a secret value out of the broker."""


@dataclass(frozen=True)
class SecretRef:
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME.match(self.name):
            raise SwitchyardError(f"invalid secret name {self.name!r}")

    @classmethod
    def parse(cls, ref: str | SecretRef) -> SecretRef:
        if isinstance(ref, SecretRef):
            return ref
        if not isinstance(ref, str) or not ref.startswith(REF_PREFIX):
            raise SwitchyardError(f"not a secret reference: expected '{REF_PREFIX}<name>'")
        return cls(ref[len(REF_PREFIX) :])

    def __str__(self) -> str:
        return REF_PREFIX + self.name


class SecretBackend(Protocol):
    name: str

    def available(self) -> bool:
        """False when locked or unreachable; the broker then skips it."""
        ...

    def get(self, name: str) -> str:
        """Return the value or raise ``KeyError``."""
        ...


def _running_under_pytest() -> bool:
    return "pytest" in sys.modules


class MemoryBackend:
    """Test-only backend. Refuses to construct outside pytest unless ``allow_test_backend``."""

    def __init__(
        self, values: Mapping[str, str], *, name: str = "memory", allow_test_backend: bool = False
    ) -> None:
        if not (allow_test_backend or _running_under_pytest()):
            raise SwitchyardError(
                "MemoryBackend is a test backend; pass allow_test_backend=True deliberately"
            )
        self.name = name
        self._values = dict(values)

    def available(self) -> bool:
        return True

    def get(self, name: str) -> str:
        return self._values[name]

    def names(self) -> list[str]:
        return sorted(self._values)


class Redactor:
    """Replaces registered secret values and known credential shapes with ``[REDACTED]``. Thread-safe."""

    def __init__(self, patterns: tuple[str, ...] = DEFAULT_PATTERNS) -> None:
        self._values: set[str] = set()
        self._patterns = [re.compile(p) for p in patterns]
        self._lock = threading.Lock()

    def add(self, value: str) -> None:
        if isinstance(value, str) and len(value) >= MIN_REDACT_CHARS:
            with self._lock:
                self._values.add(value)

    def redact(self, text: str) -> str:
        with self._lock:
            values = sorted(self._values, key=len, reverse=True)
        for value in values:
            text = text.replace(value, MASK)
        for pattern in self._patterns:
            text = pattern.sub(MASK, text)
        return text

    def redact_obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list | tuple):
            return [self.redact_obj(v) for v in value]
        if isinstance(value, dict):
            return {k: self.redact_obj(v) for k, v in value.items()}
        return value


def _contains(result: Any, value: str) -> bool:
    if isinstance(result, bytes):
        return value.encode("utf-8") in result
    if isinstance(result, str):
        return value in result
    try:
        text = json.dumps(result, default=repr, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(result)
    return value in text or value in repr(result)


class SecretsBroker:
    def __init__(
        self, backends: list[Any], policy: PolicyEngine, audit: AuditSink, redactor: Redactor
    ) -> None:
        self._backends = list(backends)
        self._owned: dict[str, list[Any]] = {}  # module id -> backends it provided (ADR-0002)
        self._policy = policy
        self._audit = audit
        self._redactor = redactor

    def add_backend(self, owner: str, backend: Any) -> None:
        if backend.name in self.backend_names():
            raise SwitchyardError(f"secret backend {backend.name!r} is already provided")
        self._backends.append(backend)
        self._owned.setdefault(owner, []).append(backend)
        self._audit.append(
            actor="core", action="secret.backend_added", module=owner, detail={"backend": backend.name}
        )

    def remove_backends(self, owner: str) -> None:
        for backend in self._owned.pop(owner, []):
            self._backends = [b for b in self._backends if b is not backend]
            self._audit.append(
                actor="core", action="secret.backend_removed", module=owner, detail={"backend": backend.name}
            )

    def backend_names(self) -> list[str]:
        return [str(b.name) for b in self._backends]

    def _resolve(self, module_id: str, name: str) -> tuple[str, str]:
        for backend in self._backends:
            if not backend.available():
                continue
            try:
                return backend.get(name), backend.name
            except KeyError:
                continue
        self._audit.append(
            actor="core", action="secret.unavailable", module=module_id, detail={"secret": name}
        )
        raise SecretUnavailable(f"secret {name!r} is not available from any unlocked backend")

    def use(self, module_id: str, ref: str | SecretRef, fn: Callable[[str], T]) -> T:
        name = SecretRef.parse(ref).name
        self._policy.require_secret(module_id, name)
        value, backend = self._resolve(module_id, name)
        self._redactor.add(value)
        self._audit.append(
            actor="core", action="secret.used", module=module_id, detail={"secret": name, "backend": backend}
        )
        failure = ""
        result: Any = None
        try:
            result = fn(value)
        except Exception as exc:
            failure = type(
                exc
            ).__name__  # keep only the class: the message (and exc itself) may hold the value
        leaked = not failure and _contains(result, value)
        # Drop every reference to the value before raising, so neither the exception context nor the traceback
        # frame's locals carry it.
        del value
        if failure:
            raise SwitchyardError(f"secret use failed: {failure}")
        if leaked:
            del result
            self._audit.append(
                actor="core", action="secret.leak_blocked", module=module_id, detail={"secret": name}
            )
            raise SecretLeak(f"result of using secret {name!r} contained the secret value; blocked")
        return result  # type: ignore[no-any-return]

    def for_module(self, module_id: str) -> ModuleSecrets:
        return ModuleSecrets(self, module_id)


class ModuleSecrets:
    """What ``ctx.secrets`` returns: the broker bound to one module."""

    __slots__ = ("_broker", "_module_id")

    def __init__(self, broker: SecretsBroker, module_id: str) -> None:
        self._broker = broker
        self._module_id = module_id

    def use(self, ref: str | SecretRef, fn: Callable[[str], T]) -> T:
        return self._broker.use(self._module_id, ref, fn)
