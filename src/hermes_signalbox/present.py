"""The human format of operation results (H5 WP2; #205, #207): what a person reads in a Hermes chat
(Markdown) and at a terminal (plain text). Summary first, plain-language labels, local times, and no JSON:
the raw payload stays available with ``json=true`` in chat and ``--json`` on the command line.

Pure functions of the result: nothing here reads state, so the same result always renders the same text.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from datetime import datetime, tzinfo
from typing import Any

from hermes_signalbox import labels, reports

MARKDOWN, TEXT = "markdown", "text"
_ORDER = {"active": 0, "failed": 1}


class _Doc:
    """Collects a headline, paragraphs, bullet lists and tables, then writes them in one of the two styles."""

    def __init__(self, style: str, width: int | None = None) -> None:
        self.md = style == MARKDOWN
        self.width = None if self.md or width is None else max(40, width)  # text only: the terminal's width
        self._blocks: list[str] = []

    def code(self, text: str) -> str:
        return f"`{text}`" if self.md else text

    def bold(self, text: str) -> str:
        return f"**{text}**" if self.md else text

    def para(self, text: str) -> None:
        self._blocks.append(text)

    def bullets(self, items: Sequence[str]) -> None:
        if items:
            self._blocks.append("\n".join(f"- {item}" for item in items))

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        if not rows:
            return
        if self.md:
            lines = [_md_row(headers), "|" + "---|" * len(headers), *(_md_row(r) for r in rows)]
        else:
            widths = [max(len(str(r[i])) for r in (headers, *rows)) for i in range(len(headers))]
            if self.width is not None and sum(widths) + 2 * (len(widths) - 1) > self.width:
                # A table wider than the terminal wraps mid-row and loses its columns, so each row becomes
                # a block instead: its first cell, then "Column: value" lines wrapped to the width.
                self._blocks.append("\n\n".join(self._row_block(headers, r) for r in rows))
                return
            lines = [
                "  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()
                for r in (headers, *rows)
            ]
        self._blocks.append("\n".join(lines))

    def _row_block(self, headers: Sequence[str], row: Sequence[str]) -> str:
        lines = [str(row[0])]
        for header, cell in zip(headers[1:], row[1:], strict=True):
            if str(cell):
                lines += textwrap.wrap(
                    f"{header}: {cell}",
                    width=self.width or 100,
                    initial_indent="  ",
                    subsequent_indent="    ",
                    break_long_words=False,
                    break_on_hyphens=False,
                )
        return "\n".join(lines)

    def text(self) -> str:
        return "\n\n".join(self._blocks)


def _md_row(cells: Sequence[str]) -> str:
    clean = [str(c).replace("|", "\\|").replace("\n", " ") for c in cells]
    return ("| " + " | ".join(clean) + " |").replace("|  |", "| |")


def _when(ts: Any, tz: tzinfo | None) -> str:
    try:
        return datetime.fromisoformat(str(ts)).astimezone(tz).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(ts)


def _needs(doc: _Doc, row: Mapping[str, Any]) -> str:
    return ", ".join(f"{labels.capability(c)} ({doc.code(c)})" for c in row.get("missing_grants") or ())


def _is_module_row(value: Any) -> bool:
    return isinstance(value, Mapping) and {"id", "status", "mode", "missing_grants"} <= set(value)


def _module_table(doc: _Doc, rows: Sequence[Mapping[str, Any]], summaries: Mapping[str, str]) -> None:
    ordered = sorted(rows, key=lambda m: (_ORDER.get(str(m.get("status")), 2), str(m.get("id"))))
    body = []
    for m in ordered:
        state = labels.module_state(m)
        if m.get("status") == "failed" and m.get("error"):
            state = f"{state}: {m['error']}"
        body.append([str(m.get("id")), summaries.get(str(m.get("id")), ""), state, _needs(doc, m)])
    doc.table(["Module", "What it does", "State", "Needs"], body)


def _grant_hint(doc: _Doc, rows: Sequence[Mapping[str, Any]], prog: str) -> None:
    waiting = [m for m in rows if m.get("missing_grants") and m.get("status") != "active"]
    if waiting:
        first = min(waiting, key=lambda m: str(m.get("id")))
        command = f"{prog} module grant {first['id']} --capability {first['missing_grants'][0]}"
        doc.para(
            "Next step: a module starts once it has every permission it needs. Grant one with "
            f"{doc.code(command)}."
        )


def _module_list(
    doc: _Doc, rows: Sequence[Mapping[str, Any]], summaries: Mapping[str, str], prog: str
) -> None:
    if not rows:
        doc.para(doc.bold("No modules are installed."))
        return
    doc.para(doc.bold(reports.summarize({"kind": "health", "modules": list(rows)})["headline"]))
    _module_table(doc, rows, summaries)
    _grant_hint(doc, rows, prog)


def _module_show(doc: _Doc, m: Mapping[str, Any], prog: str) -> None:
    doc.para(f"{doc.bold(str(m['id']))} {m.get('version', '')}: {labels.module_state(m)}".replace("  ", " "))
    if m.get("summary"):
        doc.para(str(m["summary"]))
    mode = labels.MODES.get(str(m.get("mode")))
    items = []
    if m.get("error"):
        items.append(f"Error: {m['error']}")
    if mode:
        items.append(f"Start mode: {mode.label}. {mode.meaning}")
    if m.get("granted"):
        granted = ", ".join(f"{labels.capability(c)} ({doc.code(c)})" for c in m["granted"])
        items.append(f"Permissions granted: {granted}")
    if m.get("missing_grants"):
        items.append(f"Permissions still needed: {_needs(doc, m)}")
    if m.get("isolation"):
        where = "in its own process" if m["isolation"] == "subprocess" else "inside the Signalbox process"
        items.append(f"Runs {where}")
    for key, title in (
        ("net_hosts", "Network hosts"),
        ("secrets", "Secrets it may use"),
        ("programs", "Programs it may run"),
    ):
        value = m.get(key)
        if value:
            items.append(f"{title}: {value if isinstance(value, str) else ', '.join(map(str, value))}")
    source = m.get("source")
    if isinstance(source, Mapping) and source.get("kind") == "git":
        ref = doc.code(str(source.get("ref") or "?")[:7])
        items.append(f"Source: git, {source.get('url')} at {ref} (channel {source.get('channel')})")
    elif isinstance(source, Mapping) and source.get("kind") == "bundled":
        items.append("Source: bundled with Signalbox")
    if isinstance(m.get("update"), Mapping):
        items.append(f"Update: {labels.update_state(m['update'])}")
    raw_links = m.get("links")
    links: Mapping[str, Any] = raw_links if isinstance(raw_links, Mapping) else {}
    for key, title in (("homepage", "Homepage"), ("docs", "Documentation")):
        if links.get(key):
            items.append(f"{title}: {links[key]}")
    for entry in m.get("based_on") or ():
        if isinstance(entry, Mapping):
            extra = ", ".join(str(v) for v in (entry.get("license"), entry.get("url")) if v)
            items.append(f"Based on: {entry.get('name')}" + (f" ({extra})" if extra else ""))
    panels = m.get("panels")
    if panels:
        names = [str(p.get("id", p)) if isinstance(p, Mapping) else str(p) for p in panels]
        items.append(f"Dashboard panels: {', '.join(names)}")
    if m.get("requires_core_note"):
        items.append(f"Compatibility: {m['requires_core_note']}")
    if m.get("license"):
        items.append(f"License: {m['license']}")
    if m.get("host_pid"):
        items.append(f"Hosted by process {m['host_pid']}")
    doc.bullets(items)
    _grant_hint(doc, [m], prog)


def _audit_table(doc: _Doc, records: Sequence[Mapping[str, Any]], tz: tzinfo | None) -> None:
    rows = [
        [_when(r.get("ts"), tz), labels.actor(str(r.get("actor", ""))), labels.sentence(r)]
        for r in reversed(records)
    ]
    doc.table(["When", "Who", "What happened"], rows)


def _audit_verify(doc: _Doc, r: Mapping[str, Any]) -> str:
    if r.get("ok"):
        return f"{doc.bold('Audit log intact')}: {r.get('records')} records, chain verified."
    reason = r.get("reason") or "no reason recorded"
    return (
        f"{doc.bold('AUDIT LOG PROBLEM')}: the chain breaks at record {r.get('first_bad_seq')} ({reason}). "
        "Treat this as tampering until it is explained."
    )


def _report(
    doc: _Doc, r: Mapping[str, Any], summaries: Mapping[str, str], prog: str, tz: tzinfo | None
) -> None:
    kind = str(r.get("kind"))
    summary = r.get("summary") or reports.summarize(dict(r))
    doc.para(doc.bold(f"{kind.capitalize()} report: {summary['headline']}"))
    if r.get("purpose"):
        doc.para(f"This report answers: {r['purpose']}")
    if summary["lines"] and kind != "changes":
        doc.para("Needs attention:")
        doc.bullets(summary["lines"])
    if kind == "health":
        _module_table(doc, r.get("modules") or [], summaries)
        _grant_hint(doc, r.get("modules") or [], prog)
    elif kind == "usage":
        for name, _action in reports._USAGE_SOURCES:
            data = r.get(name)
            if isinstance(data, Mapping) and "unavailable" not in data:
                doc.para(doc.bold(name.capitalize()))
                doc.bullets(_flat(doc, data))
    elif kind == "security":
        _audit_table(doc, r.get("recent_denials") or [], tz)
    elif kind == "changes":
        _audit_table(doc, r.get("changes") or [], tz)


def _flat(doc: _Doc, data: Mapping[str, Any], prefix: str = "") -> list[str]:
    out: list[str] = []
    for key, value in data.items():
        name = f"{prefix}{key}"
        if value is None or value == "" or value == [] or value == {}:
            continue  # an empty field tells the reader nothing
        if isinstance(value, Mapping):
            out += _flat(doc, value, f"{name}.")
        elif isinstance(value, list | tuple):
            out.append(f"{doc.bold(name + ':')} {', '.join(_scalar(v) for v in value)}")
        else:
            out.append(f"{doc.bold(name + ':')} {_scalar(value)}")
    return out


def _scalar(value: Any) -> str:
    if isinstance(value, Mapping):
        return ", ".join(f"{k}={_scalar(v)}" for k, v in value.items() if v is not None)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _generic(doc: _Doc, result: Any) -> None:
    if result is None:
        doc.para("Done.")
    elif isinstance(result, Mapping):
        if doc.md:
            doc.bullets(_flat(doc, result) or ["Nothing to show."])
        else:  # the terminal form keeps one "key: value" per line, nested settings as dotted keys (H1 D-26)
            doc.para("\n".join(_plain_lines(result)) or "Nothing to show.")
    elif isinstance(result, list | tuple):
        if result and all(isinstance(r, Mapping) for r in result):
            keys = [k for k in result[0] if any(r.get(k) not in (None, "", [], {}) for r in result)]
            doc.table(
                keys, [[_scalar(r.get(k)) if r.get(k) is not None else "" for k in keys] for r in result]
            )
        elif result:
            doc.bullets([_scalar(r) for r in result])
        else:
            doc.para("Nothing to show.")
    else:
        doc.para(str(result))


def _plain_lines(result: Mapping[str, Any]) -> list[str]:
    lines = []
    for key, value in result.items():
        if isinstance(value, Mapping) and value and all(not isinstance(v, Mapping) for v in value.values()):
            lines += [f"{key}.{sub}: {inner}" for sub, inner in value.items()]
        else:
            lines.append(f"{key}: {value}")
    return lines


def render(
    noun: str,
    verb: str,
    result: Any,
    *,
    style: str = MARKDOWN,
    summaries: Mapping[str, str] | None = None,
    prog: str = "hermes signalbox",
    subject: str | None = None,
    tz: tzinfo | None = None,
    width: int | None = None,
) -> str:
    """``result`` of operation ``noun verb`` for a human reader. ``summaries`` maps module ids to their
    one-line descriptions; ``prog`` is the command prefix used in next-step hints; ``subject`` is the module
    the command named, for results that do not repeat it; ``tz`` is the reader's time zone (the local one
    when ``None``); ``width`` is the terminal's width for the text style (a table that does not fit is written
    as one block per row; ``None`` never reshapes, and Markdown ignores it)."""
    doc = _Doc(style, width)
    names = summaries or {}
    op = (noun, verb)
    if op == ("module", "list") and isinstance(result, list):
        _module_list(doc, result, names, prog)
    elif op == ("module", "health") and isinstance(result, Mapping) and "ok" in result:
        target = result.get("id") or subject or "The module"
        detail = str(result.get("detail") or "")
        if result["ok"]:
            doc.para(doc.bold(f"{target} is healthy") + (f": {detail}" if detail and detail != "ok" else "."))
        else:
            doc.para(doc.bold(f"{target} reports a problem") + f": {detail or 'no detail given'}")
    elif op == ("audit", "tail") and isinstance(result, list):
        if result:
            doc.para(doc.bold(f"Last {len(result)} audit records, newest first"))
            _audit_table(doc, result, tz)
        else:
            doc.para(doc.bold("The audit log is empty."))
    elif op == ("audit", "verify") and isinstance(result, Mapping):
        return _audit_verify(doc, result)
    elif op == ("report", "show") and isinstance(result, Mapping) and "kind" in result:
        _report(doc, result, names, prog, tz)
    elif op == ("module", "check_updates") and isinstance(result, list):
        if not result:
            return (
                f"{doc.bold('No git-installed modules to check.')} "
                "Bundled modules update together with Signalbox."
            )
        _generic(doc, result)
    elif _is_module_row(result):
        _module_show(
            doc, {**result, "summary": result.get("summary") or names.get(str(result["id"]), "")}, prog
        )
    else:
        _generic(doc, result)
    if op in (("module", "list"), ("audit", "tail"), ("report", "show")) or _is_module_row(result):
        doc.para(f"Raw data: add {doc.code('json=true' if doc.md else '--json')}.")
    return doc.text()
