"""Deletion-only output shortening (ADR-0008).

A module that shortens Hermes tool or terminal output never writes text the model will read. It returns the
line ranges to keep; the core rebuilds the output from the original lines, adds every line that must never be
dropped (errors, exit codes, paths), and writes the only new text itself: ``[signalbox: N lines omitted]``.
Before ranges are applied the core normalises the text deterministically: ANSI escape sequences are removed
and carriage-return progress redraws are collapsed to their last state.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable

MAX_INPUT_CHARS = 4_000_000
MAX_RANGES = 10_000
MAX_KEEP_EXTRA = 2_000
LONG_LINE = 4_000  # longer lines are always kept, never regex-scanned (M8 review: bounded work per line)

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_EXT = "py|js|mjs|ts|tsx|jsx|go|rs|java|kt|c|cc|cpp|h|hpp|rb|php|cs|toml|yaml|yml|json|md|sh|ps1|sql|html|css"
# Lines that are never dropped (acceptance: errors, exit codes and paths). Every branch is linear-time: no
# nested or overlapping quantifiers (M8 review).
MUST_KEEP = re.compile(
    r"(?i)\b(?:error|errors|err!|exception|traceback|fatal|fail|failed|failure|failures|panic|denied|refused|"
    r"warning|warn|critical|abort|aborted|segmentation fault|killed|timeout|timed out|not found|"
    r"exit code|exit status|exited|returncode|return code|forbidden|unauthorized|unauthorised|expired|"
    r"rejected|blocked|invalid)\b"
    r"|\bHTTP/\d(?:\.\d)? [45]\d\d\b"  # HTTP error status lines (R1 review)
    r"|^\s*[45]\d\d [A-Z]"  # "401 Unauthorized", "503 Service Unavailable"
    r"|\bERR!"
    r"|^E: "  # apt
    r"|\brc\s*[=:]\s*-?\d"
    r"|\b[EFW]\d{3,4}\b"  # linters: E501, F401, W605
    r"|(?<![\w/.:~])(?:[A-Za-z]:[\\/]|\.{1,2}/|~/|/)[^\s:\"']+"  # absolute, ~/ and ./ paths (not URLs)
    rf"|(?<![\w.-])[\w-]+(?:\.[\w-]+)*\.(?:{_EXT}):\d+",  # file:line
    re.MULTILINE,
)


class BudgetExceeded(Exception):
    """The scan ran past its deadline (H1 C-3). The caller keeps the text unchanged (fail open)."""


def _check(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise BudgetExceeded


def _keep_line(line: str) -> bool:
    return len(line) > LONG_LINE or MUST_KEEP.search(line) is not None


def _any_keep(parts: list[str], deadline: float | None) -> bool:
    for part in parts:
        _check(deadline)
        if _keep_line(part):
            return True
    return False


def normalise(text: str, *, deadline: float | None = None) -> str:
    """Strip ANSI sequences and collapse carriage-return redraws to their last non-empty state. A line whose
    overwritten parts contained a must-keep match is kept whole (CRs shown as spaces), so collapsing never
    hides an error (M8 review)."""
    text = _ANSI.sub("", text)
    if "\r" not in text:
        return text
    out = []
    for line in text.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if "\r" not in line:
            out.append(line)
            continue
        _check(deadline)
        parts = [p for p in line.split("\r") if p]
        if not parts:
            out.append("")
        elif _any_keep(parts[:-1], deadline):
            out.append(" ".join(parts))
        else:
            out.append(parts[-1])
    return "\n".join(out)


def must_keep(lines: list[str], *, deadline: float | None = None) -> set[int] | None:
    """Indices of lines that must survive; ``None`` when there are too many to promise that (fail open).
    Raises ``BudgetExceeded`` past ``deadline`` (each line is bounded by ``LONG_LINE``; the text is not)."""
    out: set[int] = set()
    for i, line in enumerate(lines):
        _check(deadline)
        if _keep_line(line):
            out.add(i)
            if len(out) > MAX_KEEP_EXTRA:
                return None
    return out


def rebuild(lines: list[str], ranges: Iterable[object], *, deadline: float | None = None) -> str | None:
    """Keep ``ranges`` (``[start, end)`` line indices) plus must-keep lines. ``None`` when the ranges are
    invalid, too many lines must be kept, or nothing would be removed. Work is O(R log R + N)."""
    spans: list[tuple[int, int]] = []
    for count, item in enumerate(ranges, 1):
        if count > MAX_RANGES:
            return None
        if (
            not isinstance(item, tuple | list)
            or len(item) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in item)
        ):
            return None
        start, end = max(0, item[0]), min(len(lines), item[1])
        if start < end:
            spans.append((start, end))
    forced = must_keep(lines, deadline=deadline)
    if forced is None:
        return None
    keep = bytearray(len(lines))
    spans.sort()
    reach = 0
    for start, end in spans:  # coalesced: each line is marked at most once
        start = max(start, reach)
        if start < end:
            keep[start:end] = b"\x01" * (end - start)
            reach = end
    for i in forced:
        keep[i] = 1
    if all(keep):
        return None
    out: list[str] = []
    gap = 0
    for i, line in enumerate(lines):
        if keep[i]:
            if gap:
                out.append(f"[signalbox: {gap} lines omitted]")
                gap = 0
            out.append(line)
        else:
            gap += 1
    if gap:
        out.append(f"[signalbox: {gap} lines omitted]")
    return "\n".join(out)
