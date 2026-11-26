"""M8 trimmer (spec: README.md in this directory).

Chooses which lines of long terminal and tool output to keep; the core rebuilds the text (ADR-0008), so this
module never writes text the model reads, and the core always keeps errors, exit codes and paths.

Rules, in order, for output longer than ``min_chars``:

1. Runs of identical consecutive lines keep their first line only. Progress-shaped lines (percentages,
   ``n/m`` counters, transfer rates) also collapse when only their numbers differ.
2. If more than ``max_lines`` remain, keep the first ``head`` and the last ``tail`` lines.

Settings, ``[modules.trimmer]``::

    min_chars = 4000     # 500-1000000: shorter output is left alone
    max_lines = 200      # 20-100000
    head = 60            # 1-10000
    tail = 80            # 1-10000
    tools = []           # tool_result: tool names to trim (terminal output is always eligible)
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from functools import partial
from typing import Any

from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.modkit import int_setting

_DIGITS = re.compile(r"\d+")
# Only progress-shaped lines collapse when their numbers differ; other lines collapse only when identical,
# so a changed value (``returned 1`` among ``returned 0``) is never hidden (M8 review).
_PROGRESS = re.compile(
    r"(?i)\d+(?:\.\d+)?\s*%|\b\d+\s*/\s*\d+\b|\beta\b|[kMG]i?B/s|\bit/s\b|^\s*\[\s*\d+/\d+\]"
)
# Results of file-writing tools carry Hermes's security-guidance warnings; Hermes keeps only the first
# transform result, so these are never trimmed.
WRITE_TOOLS = frozenset({"write_file", "patch", "edit_file", "apply_patch", "str_replace", "create_file"})
_TOOL = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")


_int_setting = partial(int_setting, "trimmer")


def plan(lines: Sequence[str], max_lines: int, head: int, tail: int) -> list[list[int]]:
    """Kept ``[start, end)`` ranges (pure; used by the module and by ``preview``)."""
    kept: list[int] = []
    previous = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        shape = _DIGITS.sub("#", stripped) if _PROGRESS.search(stripped) else stripped
        if shape and shape == previous:
            continue
        previous = shape
        kept.append(i)
    if len(kept) > max_lines:
        kept = kept[:head] + kept[-tail:]
    ranges: list[list[int]] = []
    for i in kept:
        if ranges and ranges[-1][1] == i:
            ranges[-1][1] = i + 1
        else:
            ranges.append([i, i + 1])
    return ranges


class TrimmerModule:
    def __init__(self) -> None:
        self.ctx: Any = None
        self.settings: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stats: dict[str, list[int]] = {}

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        unknown = set(cfg) - {"min_chars", "max_lines", "head", "tail", "tools"}
        if unknown:
            raise SignalboxError(f"unknown [modules.trimmer] setting(s) {sorted(unknown)}")
        tools = cfg.get("tools", [])
        if (
            not isinstance(tools, list)
            or len(tools) > 64
            or not all(isinstance(t, str) and _TOOL.match(t) for t in tools)
        ):
            raise SignalboxError("[modules.trimmer] tools must be a list of tool names")
        if WRITE_TOOLS & set(tools):
            raise SignalboxError(
                f"[modules.trimmer] file-writing tools cannot be trimmed: {sorted(WRITE_TOOLS & set(tools))}"
            )
        self.settings = {
            "min_chars": _int_setting(cfg, "min_chars", 4000, 500, 1_000_000),
            "max_lines": _int_setting(cfg, "max_lines", 200, 20, 100_000),
            "head": _int_setting(cfg, "head", 60, 1, 10_000),
            "tail": _int_setting(cfg, "tail", 80, 1, 10_000),
            "tools": frozenset(tools),
        }
        if self.settings["head"] + self.settings["tail"] > self.settings["max_lines"]:
            raise SignalboxError("[modules.trimmer] head + tail must not exceed max_lines")
        ctx.state.create_table(
            "stats",
            [("tool", "TEXT"), ("calls", "INTEGER"), ("chars_in", "INTEGER"), ("chars_out", "INTEGER")],
            primary_key=["tool"],
        )
        ctx.register_action("report", self.report, params={}, read_only=True)
        ctx.register_action("preview", self.preview, params={"text": str}, read_only=False)
        ctx.register_panel("trimmer.status", self.report)
        self.ctx = ctx
        ctx.hermes_transform("terminal_output", self.on_terminal)
        ctx.hermes_transform("tool_result", self.on_tool)

    def deactivate(self) -> None:
        self.flush()
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        return (self.ctx is not None, "running" if self.ctx is not None else "stopped")

    # transforms ---------------------------------------------------------------------------------------

    def _ranges(self, lines: tuple[str, ...], tool: str) -> list[list[int]] | None:
        size = sum(len(line) + 1 for line in lines)
        if size < self.settings["min_chars"]:
            return None
        ranges = plan(lines, self.settings["max_lines"], self.settings["head"], self.settings["tail"])
        kept = sum(sum(len(lines[i]) + 1 for i in range(a, b)) for a, b in ranges)
        with self._lock:  # counted in memory; written on flush (no database write on the tool path)
            row = self._stats.setdefault(tool[:64], [0, 0, 0])
            row[0] += 1
            row[1] += size
            row[2] += kept
        return ranges

    def on_terminal(self, lines: tuple[str, ...], meta: dict[str, Any]) -> list[list[int]] | None:
        return self._ranges(lines, "terminal")

    def on_tool(self, lines: tuple[str, ...], meta: dict[str, Any]) -> list[list[int]] | None:
        tool = str(meta.get("tool_name") or "")
        if tool not in self.settings["tools"]:
            return None
        return self._ranges(lines, tool)

    # actions ------------------------------------------------------------------------------------------

    def flush(self) -> None:
        if self.ctx is None:
            return
        with self._lock:
            pending, self._stats = self._stats, {}
        t = self.ctx.state.table("stats")
        for tool, (calls, chars_in, chars_out) in pending.items():
            self.ctx.state.execute(
                f"INSERT INTO {t} VALUES (?, ?, ?, ?) ON CONFLICT(tool) DO UPDATE SET "  # nosec B608
                "calls = calls + excluded.calls, chars_in = chars_in + excluded.chars_in, "
                "chars_out = chars_out + excluded.chars_out",
                (tool, calls, chars_in, chars_out),
            )

    def report(self) -> dict[str, Any]:
        self.flush()
        t = self.ctx.state.table("stats")
        rows = self.ctx.state.execute(f"SELECT tool, calls, chars_in, chars_out FROM {t} ORDER BY tool")  # nosec B608
        tools = [
            {
                "tool": tool,
                "calls": calls,
                "chars_in": cin,
                "chars_out": cout,
                "saved_percent": round(100 * (cin - cout) / cin, 1) if cin else 0.0,
            }
            for tool, calls, cin, cout in rows
        ]
        return {
            "tools": tools,
            "settings": {k: sorted(v) if isinstance(v, frozenset) else v for k, v in self.settings.items()},
        }

    def preview(self, text: str) -> dict[str, Any]:
        """Human-only: how a text would be shortened (core rebuild, so must-keep lines show)."""
        from hermes_signalbox import trim

        if len(text) > trim.MAX_INPUT_CHARS:
            raise SignalboxError("text too long")
        lines = trim.normalise(text).split("\n")
        out = trim.rebuild(
            lines, plan(lines, self.settings["max_lines"], self.settings["head"], self.settings["tail"])
        )
        result = out if out is not None else "\n".join(lines)
        return {"chars_in": len(text), "chars_out": len(result), "text": result}
