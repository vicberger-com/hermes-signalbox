"""Deterministic routing decisions. Pure functions: no I/O, no clock, no randomness.

A request is sized (estimated tokens, tools, images) and given a tier T1 to T5. Candidates come from the
resource registry in the consumer's pool order; the engine filters them (state, capability tags, context
window, cool-down, paid gating) and orders them free first, keeping pool order within each cost class.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

TIERS = ("T1", "T2", "T3", "T4", "T5")
TIER_CEILINGS = (2_000, 8_000, 32_000, 128_000)  # estimated tokens; T5 is everything above
OUTPUT_RESERVE = 1_024  # tokens left for the answer when checking a context window
_COST_RANK = {"free": 0, "self-hosted": 0, "paid": 1}


@dataclass(frozen=True)
class Need:
    tokens: int
    tools: bool
    vision: bool
    tier: str


@dataclass(frozen=True)
class Candidate:
    id: str
    model: str
    cost_class: str
    state: str
    tags: frozenset[str]
    context: int | None


def _text_size(content: Any) -> tuple[int, bool]:
    if isinstance(content, str):
        return len(content), False
    size, image = 0, False
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                kind = str(part.get("type", ""))
                if "image" in kind:
                    image = True
                text = part.get("text")
                if isinstance(text, str):
                    size += len(text)
    return size, image


def tier_for(tokens: int) -> str:
    for tier, ceiling in zip(TIERS, TIER_CEILINGS, strict=False):
        if tokens <= ceiling:
            return tier
    return TIERS[-1]


def need_for(request: Mapping[str, Any]) -> Need:
    """Size a provider request (OpenAI-style ``messages`` and ``tools``). Never keeps any text."""
    chars, vision = 0, False
    messages = request.get("messages")
    for message in messages if isinstance(messages, list) else ():
        if isinstance(message, dict):
            size, image = _text_size(message.get("content"))
            chars += size
            vision = vision or image
    tools = request.get("tools")
    has_tools = isinstance(tools, list) and bool(tools)
    if has_tools:
        chars += len(json.dumps(tools, default=str))
    tokens = chars // 4 + 1
    return Need(tokens=tokens, tools=has_tools, vision=vision, tier=tier_for(tokens))


def candidates_from(resources: Iterable[Mapping[str, Any]], provider: str) -> list[Candidate]:
    """Registry rows (``resources.resolve``) of the active provider, as candidates, in pool order."""
    out = []
    prefix = provider + "/"
    for row in resources:
        rid = row.get("id")
        if row.get("kind") != "model" or row.get("provider") != provider:
            continue
        if not isinstance(rid, str) or not rid.startswith(prefix) or len(rid) == len(prefix):
            continue
        raw_limits, raw_tags = row.get("limits"), row.get("tags")
        limits: Mapping[str, Any] = raw_limits if isinstance(raw_limits, dict) else {}
        context = limits.get("context")
        tags: list[Any] = raw_tags if isinstance(raw_tags, list) else []
        out.append(
            Candidate(
                id=rid,
                model=rid[len(prefix) :],
                cost_class=str(row.get("cost_class", "paid")),
                state=str(row.get("state", "")),
                tags=frozenset(t for t in tags if isinstance(t, str)),
                context=context if isinstance(context, int) and not isinstance(context, bool) else None,
            )
        )
    return out


def unfit(c: Candidate, need: Need, *, cooling: Mapping[str, Any], paid_ok: bool) -> str | None:
    """Why ``c`` cannot serve ``need`` (``None`` if it can). State is checked by the caller."""
    if c.id in cooling:
        return "cooling down"
    if c.cost_class not in _COST_RANK:
        return "unknown cost class"
    if c.cost_class == "paid" and not paid_ok:
        return "paid not allowed"
    if need.tools and "tools" not in c.tags:
        return "no tool calling"
    if need.vision and "vision" not in c.tags:
        return "no image input"
    if c.context is not None and c.context < need.tokens + OUTPUT_RESERVE:
        return "context too small"
    return None


def rank(
    candidates: Sequence[Candidate], need: Need, *, cooling: Mapping[str, Any], paid_ok: bool
) -> tuple[list[Candidate], dict[str, str]]:
    """Usable automatic candidates (state ``auto``) ordered free first, then pool order; plus skip reasons."""
    usable: list[Candidate] = []
    skipped: dict[str, str] = {}
    for c in candidates:
        reason = (
            "not automatic (state manual)"
            if c.state != "auto"
            else unfit(c, need, cooling=cooling, paid_ok=paid_ok)
        )
        if reason is None:
            usable.append(c)
        else:
            skipped[c.id] = reason
    usable.sort(key=lambda c: _COST_RANK[c.cost_class])  # stable: pool order within a cost class
    return usable, skipped
