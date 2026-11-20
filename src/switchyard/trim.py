"""Deletion-only output shortening (ADR-0008).

A module that shortens Hermes tool or terminal output never writes text the model will read. It returns the
line ranges to keep; the core rebuilds the output from the original lines, adds every line that must never be
dropped (errors, exit codes, paths), and writes the only new text itself: ``[switchyard: N lines omitted]``.
Before ranges are applied the core normalises the text deterministically: ANSI escape sequences are removed
and carriage-return progress redraws are collapsed to their last state.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_INPUT_CHARS = 4_000_000
MAX_RANGES = 10_000
MAX_KEEP_EXTRA = 2_000

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
# Lines that are never dropped (acceptance: errors, exit codes and paths).
MUST_KEEP = re.compile(
    r"(?i)(\b(error|errors|exception|traceback|fatal|fail|failed|failure|failures|panic|denied|refused|"
    r"warning|warn|critical|abort(ed)?|segmentation fault|killed|timeout|timed out|not found|"
    r"exit (code|status)|returncode|return code)\b"
    r"|\b[EFW]\d{3,4}\b"  # linters: E501, F401, W605
    r"|(?<![\w/.:])(?:[A-Za-z]:[\\/]|\.{0,2}/|~/)[^\s:\"']*[\\/]?[^\s:\"']+"  # absolute, ~/ and ./ paths
    r"|\b[\w.-]+\.(py|js|ts|tsx|go|rs|java|c|cc|cpp|h|rb|php|cs|toml|yaml|yml|json|md|sh|ps1):\d+)"
)


def normalise(text: str) -> str:
    """Strip ANSI sequences and collapse carriage-return redraws (keeps each line's final state)."""
    text = _ANSI.sub("", text)
    if "\r" in text:
        text = "\n".join(
            line.rsplit("\r", 1)[-1] if line.strip("\r") else ""
            for line in text.replace("\r\n", "\n").split("\n")
        )
    return text


def must_keep(lines: list[str]) -> set[int]:
    out: set[int] = set()
    for i, line in enumerate(lines):
        if MUST_KEEP.search(line):
            out.add(i)
            if len(out) >= MAX_KEEP_EXTRA:
                break
    return out


def rebuild(lines: list[str], ranges: Iterable[object]) -> str | None:
    """Keep ``ranges`` (``[start, end)`` line indices) plus must-keep lines. ``None`` when the ranges are
    invalid or nothing would be removed."""
    keep: set[int] = set()
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
        keep.update(range(start, end))
    keep |= must_keep(lines)
    if len(keep) >= len(lines):
        return None
    out: list[str] = []
    gap = 0
    for i, line in enumerate(lines):
        if i in keep:
            if gap:
                out.append(f"[switchyard: {gap} lines omitted]")
                gap = 0
            out.append(line)
        else:
            gap += 1
    if gap:
        out.append(f"[switchyard: {gap} lines omitted]")
    return "\n".join(out)
