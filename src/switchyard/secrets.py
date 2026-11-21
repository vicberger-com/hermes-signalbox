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

import base64
import json
import re
import threading
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from switchyard.capabilities import AuditSink, PolicyEngine
from switchyard.errors import NotAvailable, SwitchyardError

T = TypeVar("T")
REF_PREFIX = "secret://"
_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
MIN_REDACT_CHARS = 4
# Distinct secret values the redactor remembers (H1 A-24). Least recently used values drop out first; a value
# is refreshed each time it is used, and a removed backend's values are forgotten at once.
MAX_REDACT_VALUES = 256
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


class SecretUnavailable(NotAvailable):
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
        """False only when the backend does not exist here (wrong platform, helper not installed); the broker
        then skips it. A locked or unreachable backend must raise from ``get`` instead, so lookups fail closed
        rather than falling through to a later backend."""
        ...

    def get(self, name: str) -> str:
        """Return the value or raise ``KeyError``."""
        ...


class MemoryBackend:
    """Test-only backend: a plain dict. Refuses to construct without ``allow_test_backend=True`` (H1 A-17: the
    old "running under pytest" check could be satisfied by any module named ``pytest``)."""

    def __init__(
        self, values: Mapping[str, str], *, name: str = "memory", allow_test_backend: bool = False
    ) -> None:
        if not allow_test_backend:
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
        self._values: OrderedDict[str, str] = OrderedDict()  # value -> source backend, oldest first
        self._by_length: list[str] | None = None  # cached longest-first order
        self._patterns = [re.compile(p) for p in patterns]
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)

    def add(self, value: str, source: str = "") -> None:
        """Remember ``value`` (from backend ``source``) as the most recently used; drop the oldest past
        ``MAX_REDACT_VALUES``."""
        if isinstance(value, str) and len(value) >= MIN_REDACT_CHARS:
            with self._lock:
                self._values[value] = source
                self._values.move_to_end(value)
                while len(self._values) > MAX_REDACT_VALUES:
                    self._values.popitem(last=False)
                self._by_length = None

    def forget_source(self, source: str) -> None:
        """Drop every value that came from backend ``source`` (its module was deactivated or removed)."""
        with self._lock:
            for value in [v for v, s in self._values.items() if s == source]:
                del self._values[value]
            self._by_length = None

    def redact(self, text: str) -> str:
        with self._lock:
            if self._by_length is None:
                self._by_length = sorted(self._values, key=len, reverse=True)
            values = self._by_length
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
            return {self.redact(k) if isinstance(k, str) else k: self.redact_obj(v) for k, v in value.items()}
        return value


def _forms(value: str) -> list[str]:
    """The value and common encodings of it; for long values also overlapping 12-character pieces. A
    tripwire for careless code, not a control against a module that wants to leak (R1 review)."""
    raw = value.encode("utf-8")
    forms = {
        value,
        raw.hex(),
        base64.b64encode(raw).decode(),
        base64.urlsafe_b64encode(raw).decode().rstrip("="),
        urllib.parse.quote(value, safe=""),
    }
    # Case changes and pieces only for long values: short ones match ordinary text (R1 follow-up).
    if len(value) >= 12:
        forms.update({value.lower(), value.upper()})
    if len(value) >= 24:
        forms.update(value[i : i + 16] for i in range(0, len(value) - 15, 8))
    return [f for f in forms if len(f) >= MIN_REDACT_CHARS]


def _contains(result: Any, value: str) -> bool:
    if isinstance(result, bytes):
        text = result.decode("utf-8", errors="replace")
    elif isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, default=repr, ensure_ascii=False)
        except (TypeError, ValueError):
            text = repr(result)
    return any(form in text for form in _forms(value))


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
            self._redactor.forget_source(str(backend.name))
            self._audit.append(
                actor="core", action="secret.backend_removed", module=owner, detail={"backend": backend.name}
            )

    def backend_names(self) -> list[str]:
        return [str(b.name) for b in self._backends]

    def _resolve(self, module_id: str, name: str) -> tuple[str, str]:
        for backend in self._backends:
            try:
                if not backend.available():
                    continue
                return backend.get(name), backend.name
            except KeyError:
                continue
            except SwitchyardError:
                raise  # our own messages (SecretLocked, ...) carry no value
            except Exception as exc:  # H1 A-18: a backend's message may hold the value; keep the class
                kind = type(exc).__name__
                detail = {"secret": name, "backend": str(backend.name), "error": kind}
                self._audit.append(
                    actor="core", action="secret.backend_error", module=module_id, detail=detail
                )
                raise SecretUnavailable(
                    f"secret {name!r}: backend {backend.name!r} failed ({kind})"
                ) from None
        self._audit.append(
            actor="core", action="secret.unavailable", module=module_id, detail={"secret": name}
        )
        raise SecretUnavailable(f"secret {name!r} is not available from any unlocked backend")

    def use(self, module_id: str, ref: str | SecretRef, fn: Callable[[str], T]) -> T:
        name = SecretRef.parse(ref).name
        self._policy.require_secret(module_id, name)
        value, backend = self._resolve(module_id, name)
        if len(value) < MIN_REDACT_CHARS:  # too short to redact reliably (R1 review)
            del value
            raise SwitchyardError(f"secret {name!r} is shorter than {MIN_REDACT_CHARS} characters; refused")
        self._redactor.add(value, backend)
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
