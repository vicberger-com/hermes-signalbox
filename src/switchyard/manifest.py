"""Load and validate ``module.toml`` against the packaged schema (spec section 3, Manifest).

Standard library only. ``check`` supports exactly the JSON Schema keywords the schema uses and raises on any
other keyword, so the schema cannot quietly rely on something this validator ignores. ``pattern`` follows
JSON Schema (ECMA-262) semantics for a trailing ``$``: it does not match before a final newline.

Cross-field rules enforced in addition to the schema:

* ``net.outbound`` is requested if and only if ``capabilities.net_hosts`` is non-empty.
* ``secrets.read`` is requested if and only if ``capabilities.secrets`` is non-empty.
* ``license_class = "proprietary-connector"`` requires ``isolation = "subprocess"``.
* ``update.source = "git"`` requires ``update.url`` and a full commit SHA in ``update.ref``.
* ``lifecycle.idle_stop_seconds`` above zero requires ``activation = "auto"``.
* ``module.id`` may not contain ``__`` (it would collide with state-store table prefixes ``m_<id>__``).

Core checks in ``load_manifest``: file size limit, no empty dotted parts in ``entry``, and the entry module
file must exist inside the module directory after resolving symlinks.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any

from switchyard.errors import ManifestError

MANIFEST_NAME = "module.toml"
MAX_MANIFEST_BYTES = 64 * 1024
CONTRIBUTION_KINDS: tuple[str, ...] = (
    "hooks", "tools", "commands", "panels", "policies", "triggers", "log_streams",
)  # fmt: skip

_TYPES: dict[str, type] = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
_ANNOTATIONS = {"$schema", "$id", "title", "description"}
_SUPPORTED = _ANNOTATIONS | {
    "type", "const", "enum", "pattern", "minimum", "items", "uniqueItems",
    "properties", "required", "additionalProperties",
}  # fmt: skip


@cache
def load_schema() -> dict[str, Any]:
    """The normative schema shipped inside the package."""
    text = resources.files("switchyard").joinpath("schemas", "module.schema.json").read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


@cache
def _compile(pattern: str) -> re.Pattern[str]:
    # ECMA-262 `$` (without the m flag) matches only at the very end; Python's also matches before "\n".
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


def check(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Return a list of human-readable errors for ``value`` against ``schema`` (empty when valid)."""
    unknown = set(schema) - _SUPPORTED
    if unknown:
        raise ValueError(f"{path}: unsupported schema keyword(s): {sorted(unknown)}")

    kind = schema.get("type")
    if kind is not None and (
        not isinstance(value, _TYPES[kind]) or (kind == "integer" and isinstance(value, bool))
    ):
        return [f"{path}: expected {kind}, got {type(value).__name__}"]

    errors: list[str] = []
    if "const" in schema and (value != schema["const"] or isinstance(value, bool)):
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if "pattern" in schema and isinstance(value, str) and not _compile(schema["pattern"]).search(value):
        errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if "minimum" in schema and isinstance(value, int) and value < schema["minimum"]:
        errors.append(f"{path}: must be >= {schema['minimum']}")

    if isinstance(value, list):
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errors.append(f"{path}: items must be unique")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(check(item, schema["items"], f"{path}[{i}]"))

    if isinstance(value, dict):
        props: Mapping[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
        for key, item in value.items():
            if key in props:
                errors.extend(check(item, props[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown key {key!r}")
    return errors


def _section(doc: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = doc.get(key)
    return value if isinstance(value, Mapping) else {}


def cross_field(doc: Mapping[str, Any]) -> list[str]:
    """Rules that span fields. Tolerates missing sections; the schema reports those."""
    errors: list[str] = []
    module, caps, life, update = (_section(doc, k) for k in ("module", "capabilities", "lifecycle", "update"))
    raw = caps.get("request")
    requested: list[Any] = raw if isinstance(raw, list) else []

    for cap, field in (("net.outbound", "net_hosts"), ("secrets.read", "secrets")):
        if (cap in requested) != bool(caps.get(field)):
            errors.append(f"$.capabilities: {cap!r} must be requested exactly when {field!r} is non-empty")
    if module.get("license_class") == "proprietary-connector" and module.get("isolation") != "subprocess":
        errors.append("$.module: a proprietary-connector must use isolation = 'subprocess'")
    if update.get("source") == "git" and not (update.get("url") and update.get("ref")):
        errors.append("$.update: source = 'git' requires 'url' and a full commit SHA in 'ref'")
    if life.get("idle_stop_seconds", 0) and life.get("activation") != "auto":
        errors.append("$.lifecycle: idle_stop_seconds > 0 requires activation = 'auto'")
    if "__" in str(module.get("id", "")):
        errors.append("$.module.id: must not contain '__'")
    return errors


def validate_document(doc: Mapping[str, Any]) -> list[str]:
    """Validate a parsed manifest. Returns all errors."""
    return check(doc, load_schema()) + cross_field(doc)


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ManifestError(path, [f"cannot read manifest: {exc}"]) from exc
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError(path, [f"manifest too large (limit {MAX_MANIFEST_BYTES} bytes)"])
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(path, [f"cannot read manifest: {exc}"]) from exc


def validate_file(path: Path) -> list[str]:
    """Validate a manifest file; read failures are reported as a single error."""
    try:
        doc = _read(path)
    except ManifestError as exc:
        return [f"{path}: {e}" for e in exc.errors]
    return validate_document(doc)


@dataclass(frozen=True)
class Manifest:
    """A validated module manifest. Built only by ``load_manifest``."""

    path: Path
    directory: Path
    id: str
    name: str
    version: str
    license: str
    license_class: str
    summary: str
    requires_core: str
    isolation: str
    entry_module: str
    entry_class: str
    entry_file: Path
    requested: frozenset[str]
    net_hosts: tuple[str, ...]
    secrets: tuple[str, ...]
    contributes: Mapping[str, tuple[str, ...]]
    activation: str
    idle_stop_seconds: int
    update_source: str
    update_url: str | None
    update_ref: str | None


def _entry_file(directory: Path, entry_module: str) -> Path:
    parts = entry_module.split(".")
    if any(not p for p in parts):
        raise ValueError(f"entry {entry_module!r} has an empty dotted part")
    base = directory.joinpath(*parts)
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            if not candidate.resolve().is_relative_to(directory.resolve()):
                raise ValueError(f"entry module {entry_module!r} resolves outside the module directory")
            return candidate
    raise ValueError(f"entry module {entry_module!r} not found in the module directory")


def load_manifest(path: Path) -> Manifest:
    """Load ``path`` (a ``module.toml`` or its directory). ``ManifestError`` lists every problem."""
    path = path / MANIFEST_NAME if path.is_dir() else path
    doc = _read(path)
    errors = validate_document(doc)
    if errors:
        raise ManifestError(path, errors)

    module, caps, life = doc["module"], doc["capabilities"], doc["lifecycle"]
    update = _section(doc, "update")
    directory = path.parent
    entry_module, entry_class = module["entry"].split(":", 1)
    try:
        entry_file = _entry_file(directory, entry_module)
    except ValueError as exc:
        raise ManifestError(path, [str(exc)]) from None

    contributes = _section(doc, "contributes")
    return Manifest(
        path=path,
        directory=directory,
        id=module["id"],
        name=module["name"],
        version=module["version"],
        license=module["license"],
        license_class=module["license_class"],
        summary=module["summary"],
        requires_core=module["requires_core"],
        isolation=module["isolation"],
        entry_module=entry_module,
        entry_class=entry_class,
        entry_file=entry_file,
        requested=frozenset(caps["request"]),
        net_hosts=tuple(caps.get("net_hosts", ())),
        secrets=tuple(caps.get("secrets", ())),
        contributes=MappingProxyType({k: tuple(contributes.get(k, ())) for k in CONTRIBUTION_KINDS}),
        activation=life["activation"],
        idle_stop_seconds=life.get("idle_stop_seconds", 0),
        update_source=update.get("source", "bundled"),
        update_url=update.get("url"),
        update_ref=update.get("ref"),
    )
