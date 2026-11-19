"""Validate a Switchyard ``module.toml`` against ``schemas/module.schema.json``.

Standard library only. Supports exactly the JSON Schema keywords the schema uses and raises on any
other keyword, so the schema cannot quietly rely on something this validator ignores.

Cross-field rules enforced in addition to the schema:

* ``net.outbound`` is requested if and only if ``capabilities.net_hosts`` is non-empty.
* ``secrets.read`` is requested if and only if ``capabilities.secrets`` is non-empty.
* ``license_class = "proprietary-connector"`` requires ``isolation = "subprocess"``.
* ``update.source = "git"`` requires ``update.url`` and a full commit SHA in ``update.ref``.
* ``lifecycle.idle_stop_seconds`` above zero requires ``activation = "auto"``.

Usage: ``python tools/validate_manifest.py path/to/module.toml [...]``. Exit code 0 when all are valid.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "module.schema.json"

_TYPES: dict[str, type] = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
_ANNOTATIONS = {"$schema", "$id", "title", "description"}
_SUPPORTED = _ANNOTATIONS | {
    "type", "const", "enum", "pattern", "minimum", "items", "uniqueItems",
    "properties", "required", "additionalProperties",
}  # fmt: skip


def check(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
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
    if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
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
        props: dict[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
        for key, item in value.items():
            if key in props:
                errors.extend(check(item, props[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown key {key!r}")
    return errors


def _section(doc: dict[str, Any], key: str) -> dict[str, Any]:
    value = doc.get(key)
    return value if isinstance(value, dict) else {}


def cross_field(doc: dict[str, Any]) -> list[str]:
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
    return errors


def validate_document(doc: dict[str, Any]) -> list[str]:
    """Validate a parsed manifest. Returns all errors."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return check(doc, schema) + cross_field(doc)


def validate_file(path: Path) -> list[str]:
    """Validate a manifest file. A file that is not valid TOML yields a single error."""
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"{path}: cannot read manifest: {exc}"]
    return validate_document(doc)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    failed = False
    for name in argv:
        errors = validate_file(Path(name))
        if errors:
            failed = True
            print(f"INVALID {name}")
            for err in errors:
                print(f"  {err}")
        else:
            print(f"ok      {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
