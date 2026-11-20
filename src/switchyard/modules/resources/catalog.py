"""Catalog parsers for the resource registry. Every source is untrusted input: only listed fields are kept,
every field is type-checked, ids follow one pattern, and the number of rows is capped."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from switchyard.errors import SwitchyardError

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}\Z")
TAG = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}\Z")
KINDS = ("model", "endpoint", "agent", "tool")
COST_CLASSES = ("free", "paid", "self-hosted")
STATES = ("manual", "auto", "disabled")
MAX_ROWS = 20_000
SELF_HOSTED_PROVIDERS = frozenset({"ollama", "lmstudio", "llama.cpp", "llamacpp", "vllm", "local", "jan"})
DESCRIPTIVE = ("kind", "provider", "name", "cost_class", "tags", "limits")


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 1 << 40 else None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value >= 0 else None


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _seq(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, limit: int = 200) -> str:
    return value[:limit] if isinstance(value, str) else ""


def resource(
    rid: str,
    *,
    kind: str,
    provider: str,
    name: str,
    cost_class: str,
    tags: Iterable[str],
    limits: Mapping[str, Any],
) -> dict[str, Any]:
    if not ID.match(rid):
        raise SwitchyardError(f"invalid resource id {rid[:80]!r}")
    if kind not in KINDS or cost_class not in COST_CLASSES:
        raise SwitchyardError(f"resource {rid!r}: invalid kind or cost class")
    clean_tags = sorted({t for t in tags if isinstance(t, str) and TAG.match(t)})
    clean_limits = {k: v for k in ("context", "output") if (v := _int(limits.get(k))) is not None}
    return {
        "id": rid,
        "kind": kind,
        "provider": _text(provider, 100),
        "name": _text(name) or rid,
        "cost_class": cost_class,
        "tags": clean_tags,
        "limits": clean_limits,
    }


def from_models_dev(doc: Any, *, providers: set[str], free_only: bool) -> list[dict[str, Any]]:
    """Parse the models.dev registry (the file Hermes caches). Keeps names, limits, cost class and capability
    tags; drops everything else (API URLs, environment variable names, descriptions)."""
    if not isinstance(doc, dict):
        raise SwitchyardError("models.dev data must be an object of providers")
    out: list[dict[str, Any]] = []
    for pid, provider in doc.items():
        if not isinstance(pid, str) or not isinstance(provider, dict) or (providers and pid not in providers):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for mid, model in models.items():
            if not isinstance(mid, str) or not isinstance(model, dict):
                continue
            cost = _obj(model.get("cost"))
            prices = [_num(cost.get("input")), _num(cost.get("output"))]
            if pid.lower() in SELF_HOSTED_PROVIDERS:
                cost_class = "self-hosted"
            elif mid.endswith(":free") or (all(p is not None for p in prices) and not any(prices)):
                cost_class = "free"
            else:
                cost_class = "paid"
            if free_only and cost_class != "free":
                continue
            tags = []
            if model.get("tool_call") is True:
                tags.append("tools")
            if model.get("reasoning") is True:
                tags.append("reasoning")
            if model.get("open_weights") is True:
                tags.append("open-weights")
            inputs = _seq(_obj(model.get("modalities")).get("input"))
            if "image" in inputs:
                tags.append("vision")
            limits = _obj(model.get("limit"))
            try:
                out.append(
                    resource(
                        f"{pid}/{mid}",
                        kind="model",
                        provider=pid,
                        name=_text(model.get("name")),
                        cost_class=cost_class,
                        tags=tags,
                        limits=limits,
                    )
                )
            except SwitchyardError:
                continue  # an odd id in a third-party catalog is skipped, not fatal
            if len(out) > MAX_ROWS:
                raise SwitchyardError(f"catalog has more than {MAX_ROWS} resources; filter by provider")
    return out


def from_file(doc: Any) -> list[dict[str, Any]]:
    """Switchyard's own catalog format: ``{"resources": [{"id", "kind", "provider", "name", "cost_class",
    "tags", "limits"}]}``. Invalid entries are errors (a reviewed file should be clean)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("resources"), list):
        raise SwitchyardError("catalog file must be an object with a 'resources' list")
    rows = doc["resources"]
    if len(rows) > MAX_ROWS:
        raise SwitchyardError(f"catalog has more than {MAX_ROWS} resources")
    out = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise SwitchyardError(f"resources[{index}]: expected an object with a string 'id'")
        tags = row.get("tags", [])
        raw_limits = row.get("limits", {})
        limits: dict[str, Any] = raw_limits if isinstance(raw_limits, dict) else {}
        out.append(
            resource(
                row["id"],
                kind=row.get("kind", "model"),
                provider=_text(row.get("provider")),
                name=_text(row.get("name")),
                cost_class=row.get("cost_class", "paid"),
                tags=tags if isinstance(tags, list) else [],
                limits=limits,
            )
        )
    return out


def diff(existing: Mapping[str, dict[str, Any]], incoming: list[dict[str, Any]]) -> dict[str, Any]:
    """``existing`` holds the resources previously imported from the same source."""
    seen = {r["id"]: r for r in incoming}
    added = [r for rid, r in seen.items() if rid not in existing]
    changed = []
    for rid, new in seen.items():
        old = existing.get(rid)
        if old is not None and any(old.get(k) != new.get(k) for k in DESCRIPTIVE):
            changed.append(
                {
                    "id": rid,
                    "before": {k: old.get(k) for k in DESCRIPTIVE},
                    "after": {k: new.get(k) for k in DESCRIPTIVE},
                }
            )
    removed = sorted(rid for rid in existing if rid not in seen)
    return {"added": added, "changed": changed, "removed": removed}
