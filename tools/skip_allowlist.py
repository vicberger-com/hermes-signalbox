"""Per-platform skip allow-list for the test suite (H1, finding D-12).

``tests/conftest.py`` records every skipped and passed test. With ``SIGNALBOX_CHECK_SKIPS=1`` (set in CI) the
session fails when a test skips that is not listed for this platform in ``tests/skip_allowlist.json``, or when
a listed test ran and passed (the list is stale). Each OS proves its own half, and a new silent skip on any
OS turns the run red.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path

ALLOWLIST = Path(__file__).resolve().parent.parent / "tests" / "skip_allowlist.json"


def allowed(platform: str | None = None, path: Path = ALLOWLIST) -> frozenset[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get(platform or sys.platform, [])
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise ValueError(f"{path.name}: entries for {platform!r} must be a list of test ids")
    return frozenset(entries)


def _base(nodeid: str) -> str:
    return nodeid.split("[", 1)[0]  # parametrized cases share one entry


def compare(skipped: Iterable[str], passed: Iterable[str], expected: frozenset[str]) -> list[str]:
    """Problems: tests that skipped without being listed, and listed tests that passed."""
    skipped_ids = {_base(n) for n in skipped}
    passed_ids = {_base(n) for n in passed}
    problems = [f"unexpected skip: {n}" for n in sorted(skipped_ids - expected)]
    problems += [f"listed as skipped but ran: {n}" for n in sorted((expected & passed_ids) - skipped_ids)]
    return problems
