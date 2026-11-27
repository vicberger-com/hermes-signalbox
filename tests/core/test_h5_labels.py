"""H5 WP2 (#205, #207, #208): one label source, report summaries, and the human formatter for chat and CLI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from sy_testing import write_module

from hermes_signalbox import labels, present, reports
from hermes_signalbox.capabilities import CAPABILITIES
from hermes_signalbox.cli import main
from hermes_signalbox.core import Core
from hermes_signalbox.discovery import ModuleStatus
from hermes_signalbox.hermes import HermesAdapter
from hermes_signalbox.lifecycle import MODES
from hermes_signalbox.notify import SEVERITIES

ROOT = Path(__file__).resolve().parents[2]


def _row(mid: str, status: str = "verified", mode: str = "auto", missing: tuple[str, ...] = (),
         error: str | None = None) -> dict[str, Any]:  # fmt: skip
    requested = sorted(missing)
    return {
        "id": mid, "version": "0.1.0", "status": status, "mode": mode, "isolation": "in-process",
        "error": error, "requested": requested, "granted": [], "missing_grants": requested,
    }  # fmt: skip


def _rec(seq: int, action: str, module: str = "router", actor: str = "cli", **detail: str) -> dict[str, Any]:
    return {
        "seq": seq, "ts": f"2026-11-25T20:{seq:02d}:00.000000+00:00", "actor": actor, "action": action,
        "module": module, "detail": detail, "prev": "p" * 8, "hash": "h" * 8,
    }  # fmt: skip


# labels: completeness ---------------------------------------------------------------------------------


def test_h5_wp2_every_capability_status_mode_and_severity_has_a_label() -> None:
    assert set(labels.CAPABILITIES) == set(CAPABILITIES)
    assert set(labels.STATUSES) == {s.value for s in ModuleStatus}
    assert set(labels.MODES) == set(MODES)
    assert set(labels.SEVERITIES) == set(SEVERITIES)
    for table in (labels.CAPABILITIES, labels.STATUSES, labels.MODES, labels.SEVERITIES, labels.ACTIONS):
        for key, entry in table.items():
            assert entry.label and entry.meaning, key
            assert entry.label != key, f"{key}: the label must be plain words, not the id"


def test_h5_wp2_every_listed_core_audit_action_has_a_label() -> None:
    text = (ROOT / "docs" / "REFERENCE.md").read_text(encoding="utf-8")
    section = re.search(r"^## Audit actions\n(.*?)(?=^Module actions are recorded)", text, re.S | re.M)
    assert section is not None
    listed = set(re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", section.group(1)))
    assert len(listed) > 30
    assert listed - set(labels.ACTIONS) == set()


def test_h5_wp2_glossary_is_plain_data_and_module_actions_fall_back_readably() -> None:
    glossary = labels.glossary()
    assert set(glossary) == {"capabilities", "statuses", "modes", "severities", "actions", "actors"}
    assert glossary["capabilities"]["hermes.hooks"]["label"] == "Watch and steer Hermes requests"
    assert json.loads(json.dumps(glossary)) == glossary
    assert labels.action("module.router.hard_stop") == "Router: hard stop"
    assert labels.capability("not.a.capability") == "not.a.capability"


def test_h5_wp2_audit_records_read_as_sentences() -> None:
    granted = _rec(1, "policy.granted", capability="hermes.hooks")
    assert labels.sentence(granted) == "CLI granted router the permission to watch and steer Hermes requests"
    mode = _rec(2, "module.mode_changed", actor="api", mode="manual")
    assert labels.sentence(mode) == "Dashboard set router to manual start"
    assert labels.sentence(_rec(3, "module.activated", actor="hermes-user")) == "You (chat) started router"


@pytest.mark.parametrize(
    ("row", "state"),
    [
        (_row("a", "active"), "Running"),
        (_row("a", "failed", error="boom"), "Error"),
        (_row("a", missing=("ui.panel",)), "Ready, needs permissions"),
        (_row("a", mode="manual"), "Manual start"),
        (_row("a", mode="disabled"), "Disabled"),
        (_row("a", "stopped"), "Stopped"),
        (_row("a"), "Ready, starts with Hermes"),
    ],
)
def test_h5_wp2_module_state_in_plain_words(row: dict[str, Any], state: str) -> None:
    assert labels.module_state(row) == state


# report summaries: fixed text on known fixtures -------------------------------------------------------


def test_h5_wp2_health_summary_healthy_nothing_granted_and_failed() -> None:
    healthy = reports.summarize(
        {"kind": "health", "modules": [_row("meter", "active"), _row("router", "active")]}
    )
    assert healthy["headline"] == "2 of 2 modules running · 0 failed · 0 waiting for permissions"
    assert healthy["counts"] == {"total": 2, "running": 2, "failed": 0, "waiting_for_permissions": 0}
    assert healthy["lines"] == []

    rows = [_row("meter", missing=("hermes.hooks", "ui.panel")), _row("router", missing=("hermes.hooks",))]
    nothing = reports.summarize({"kind": "health", "modules": rows})
    assert nothing["headline"] == "0 of 2 modules running · 0 failed · 2 waiting for permissions"
    assert nothing["lines"] == [
        "meter is waiting for 2 permissions: hermes.hooks, ui.panel",
        "router is waiting for 1 permission: hermes.hooks",
    ]

    failed = reports.summarize(
        {"kind": "health", "modules": [_row("meter", "failed", error="boom"), _row("router", "active")]}
    )
    assert failed["headline"] == "1 of 2 modules running · 1 failed · 0 waiting for permissions"
    assert failed["lines"] == ["meter failed: boom"]


def test_h5_wp2_usage_summary_says_why_a_source_is_missing() -> None:
    payload = {
        "kind": "usage",
        "meter": {"unavailable": "not active"},
        "router": {"provider": "openrouter"},
        "trimmer": {"unavailable": "not installed"},
        "workers": {"unavailable": "action failed"},
    }
    rows = [
        _row("meter", missing=("hermes.hooks", "ui.panel")),
        _row("router", "active"),
        _row("workers", "active"),
    ]
    summary = reports.summarize(payload, modules=rows)
    assert summary["headline"] == "1 of 4 usage sources reporting"
    assert summary["lines"] == [
        "meter isn't running: grant hermes.hooks and ui.panel to collect its data",
        "trimmer isn't installed",
        "workers is running but its report failed: run 'module health workers'",
    ]


def test_h5_wp2_security_summary_intact_and_tampered() -> None:
    denials = [_rec(i, "policy.denied", actor="core", capability="hermes.hooks") for i in (1, 2, 3)]
    intact = reports.summarize(
        {
            "kind": "security",
            "audit": {"ok": True, "records": 72, "first_bad_seq": None, "reason": ""},
            "recent_denials": denials,
        }
    )
    assert intact["headline"] == "Audit log intact: 72 records, chain verified · 3 recent refusals"
    assert intact["counts"] == {"records": 72, "refusals": 3, "audit_ok": True}
    assert intact["lines"] == ["router: Permission refused (hermes.hooks), 3 times"]

    tampered = reports.summarize(
        {
            "kind": "security",
            "audit": {"ok": False, "records": 6, "first_bad_seq": 7, "reason": "hash mismatch"},
            "recent_denials": [],
        }
    )
    assert tampered["headline"] == (
        "AUDIT LOG PROBLEM: the chain breaks at record 7 (hash mismatch) · no recent refusals"
    )
    assert tampered["counts"]["audit_ok"] is False


def test_h5_wp2_changes_summary_lists_the_latest_as_sentences() -> None:
    changes = [_rec(1, "policy.granted", capability="ui.panel"), _rec(2, "module.activated", actor="api")]
    summary = reports.summarize({"kind": "changes", "changes": changes})
    assert summary["headline"] == "2 changes recorded; latest: Dashboard started router"
    assert summary["lines"] == [
        "Dashboard started router",
        "CLI granted router the permission to show a dashboard panel",
    ]
    assert (
        reports.summarize({"kind": "changes", "changes": []})["headline"]
        == "No changes in the recent records"
    )


def test_h5_wp2_every_report_kind_has_a_purpose_and_a_summary(tmp_path: Path) -> None:
    write_module(tmp_path / "modules", "ext", isolation="subprocess", request=("schedule",))
    assert set(reports.PURPOSES) == set(reports.KINDS)
    with Core(data_dir=tmp_path, hosting=False) as core:
        for kind in reports.KINDS:
            report = core.run("report", "show", {"kind": kind}, actor="cli")
            assert report["purpose"] == reports.PURPOSES[kind]
            assert set(report["summary"]) == {"headline", "counts", "lines"}
        again = core.run("report", "show", {"kind": "health"}, actor="cli")["summary"]
        assert (
            again == core.run("report", "show", {"kind": "health"}, actor="cli")["summary"]
        )  # deterministic
        assert again["headline"] == "0 of 1 modules running · 0 failed · 1 waiting for permissions"


# the human formatter -----------------------------------------------------------------------------------

_SUMMARIES = {"meter": "Counts every Hermes API response.", "router": "Picks the model for each request."}


def test_h5_wp2_module_list_markdown_has_summary_table_and_next_step() -> None:
    rows = [_row("router", missing=("hermes.hooks",)), _row("meter", "active")]
    text = present.render("module", "list", rows, summaries=_SUMMARIES)
    lines = text.splitlines()
    assert lines[0] == "**1 of 2 modules running · 0 failed · 1 waiting for permissions**"
    assert "| Module | What it does | State | Needs |" in lines
    table = [ln for ln in lines if ln.startswith("| ") and "---" not in ln][1:]
    assert table[0] == "| meter | Counts every Hermes API response. | Running | |"  # running first
    assert table[1] == (
        "| router | Picks the model for each request. | Ready, needs permissions "
        "| Watch and steer Hermes requests (`hermes.hooks`) |"
    )
    assert "hermes signalbox module grant router --capability hermes.hooks" in text
    assert "json=true" in text
    for raw in ('"id"', "missing_grants", "in-process", "None", "null", "{", "["):
        assert raw not in text, raw


def test_h5_wp2_text_style_is_plain_and_has_no_markdown() -> None:
    rows = [_row("router", missing=("hermes.hooks",)), _row("meter", "active")]
    text = present.render("module", "list", rows, summaries=_SUMMARIES, style="text")
    assert text.splitlines()[0] == "1 of 2 modules running · 0 failed · 1 waiting for permissions"
    assert "|" not in text and "**" not in text and "`" not in text
    assert "--json" in text and "json=true" not in text


def test_h5_wp2_show_health_audit_report_and_updates_are_readable() -> None:
    shown = {"summary": "Picks.", "license": "Apache-2.0", "host_pid": None, "panels": []}
    show = present.render("module", "show", {**_row("router", missing=("hermes.hooks",)), **shown})
    assert show.splitlines()[0] == "**router** 0.1.0: Ready, needs permissions"
    assert "Picks." in show and "Watch and steer Hermes requests" in show and "None" not in show

    assert present.render("module", "health", {"id": "meter", "ok": True, "detail": "ok"}).startswith(
        "**meter is healthy**"
    )
    assert present.render("module", "health", {"id": "meter", "ok": False, "detail": "db locked"}).startswith(
        "**meter reports a problem**: db locked"
    )

    tail = present.render("audit", "tail", [_rec(1, "policy.granted", capability="ui.panel")])
    assert "| When | Who | What happened |" in tail
    assert "CLI granted router the permission to show a dashboard panel" in tail
    assert "hhhhhhhh" not in tail  # chain hashes stay in the JSON form

    verify = present.render(
        "audit", "verify", {"ok": True, "records": 72, "first_bad_seq": None, "reason": ""}
    )
    assert verify == "**Audit log intact**: 72 records, chain verified."

    payload: dict[str, Any] = {"kind": "health", "modules": [_row("meter", "active")]}
    payload.update(purpose=reports.PURPOSES["health"], summary=reports.summarize(payload))
    report = present.render("report", "show", payload)
    assert (
        report.splitlines()[0]
        == "**Health report: 1 of 1 modules running · 0 failed · 0 waiting for permissions**"
    )
    assert reports.PURPOSES["health"] in report

    assert present.render("module", "check_updates", []) == (
        "**No git-installed modules to check.** Bundled modules update together with Signalbox."
    )


def test_h5_wp2_unknown_results_never_fall_back_to_json() -> None:
    text = present.render("module", "action", {"by": 3, "nested": {"a": 1, "b": None}, "items": []})
    assert "{" not in text and "None" not in text
    assert "- **by:** 3" in text and "- **nested.a:** 1" in text
    assert present.render("module", "grant", None) == "Done."


# surfaces: chat, CLI text, CLI --json, model tool ----------------------------------------------------


@pytest.fixture
def data(tmp_path: Path) -> Path:
    write_module(tmp_path / "modules", "ext", isolation="subprocess", request=("schedule",))
    return tmp_path


def _adapter(core: Core) -> HermesAdapter:
    adapter = HermesAdapter.__new__(HermesAdapter)
    adapter.core = core
    return adapter


def test_h5_wp2_slash_reply_is_markdown_and_json_true_is_the_old_payload(data: Path) -> None:
    with Core(data_dir=data, hosting=True) as core:
        adapter = _adapter(core)
        reply = adapter.command("module list")
        assert reply.splitlines()[0] == "**0 of 1 modules running · 0 failed · 1 waiting for permissions**"
        assert "| ext | test | Ready, needs permissions | Run on a timer (`schedule`) |" in reply
        expected = json.dumps(core.run("module", "list", {}, actor="cli"), indent=2, default=str)
        assert adapter.command("module list json=true") == expected  # byte for byte
        assert adapter.command("audit verify").startswith("**Audit log intact**")
        assert adapter.command("report show kind=health").startswith(
            "**Health report: 0 of 1 modules running"
        )


def test_h5_wp2_model_tool_output_is_unchanged(data: Path) -> None:
    with Core(data_dir=data, hosting=True) as core:
        out = json.loads(_adapter(core).tool_modules({"action": "list"}))
        assert out["ok"] is True and "**" not in json.dumps(out)
        rows = out["result"]["untrusted_data"] if isinstance(out["result"], dict) else out["result"]
        assert rows[0]["id"] == "ext" and set(rows[0]) == set(_row("x"))


def test_h5_wp2_cli_text_uses_the_formatter_and_json_flag_is_unchanged(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data-dir", str(data), "module", "list"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "0 of 1 modules running · 0 failed · 1 waiting for permissions"
    assert "ext" in out and "Ready, needs permissions" in out and "Run on a timer (schedule)" in out
    assert "hermes-signalbox module grant ext --capability schedule" in out
    assert main(["--data-dir", str(data), "--json", "module", "list"]) == 0
    [row] = json.loads(capsys.readouterr().out)
    assert set(row) == set(_row("x"))


# Q-SY-H5-CLOSE-1 (1): a table that does not fit the terminal is written as one block per row ------------

_LONG = {
    "router": "Picks the model for each Hermes request from the registry: free first, paid only by rule and "
    "budget, failover with cool-down.",
    "workers": "Worker roles and teams for Hermes delegation: each role routes to its own model pool or "
    "Hermes profile.",
}


def _wide_rows() -> list[dict[str, Any]]:
    return [
        _row("router", missing=("hermes.hooks", "ui.panel")),
        _row("workers", missing=("hermes.delegation", "hermes.hooks", "schedule", "ui.panel")),
    ]


def test_h5_close_a_wide_table_becomes_blocks_that_fit_the_terminal() -> None:
    text = present.render("module", "list", _wide_rows(), summaries=_LONG, style="text", width=80)
    table = text.split("\n\n", 1)[1].split("\n\nNext step:")[0]
    assert max(len(line) for line in table.splitlines()) <= 80
    assert table.splitlines()[0] == "router"
    for label in (
        "  What it does: Picks the model",
        "  State: Ready, needs permissions",
        "  Needs: Watch and steer",
    ):
        assert label in table, label
    squeezed = " ".join(table.split())
    assert "failover with cool-down." in squeezed and "Run sub-agents (hermes.delegation)" in squeezed
    assert "Show a dashboard panel (ui.panel)" in squeezed  # nothing is cut off


def test_h5_close_a_table_that_fits_stays_a_table_and_no_width_means_no_wrapping() -> None:
    rows = [_row("router", missing=("hermes.hooks",)), _row("meter", "active")]
    narrow = present.render("module", "list", rows, summaries=_SUMMARIES, style="text", width=200)
    assert narrow == present.render("module", "list", rows, summaries=_SUMMARIES, style="text")
    assert narrow.split("\n\n")[1].splitlines()[0].split() == [
        "Module",
        "What",
        "it",
        "does",
        "State",
        "Needs",
    ]
    unlimited = present.render("module", "list", _wide_rows(), summaries=_LONG, style="text")
    assert unlimited.split("\n\n")[1].splitlines()[0].startswith("Module ")
    chat = present.render("module", "list", _wide_rows(), summaries=_LONG, width=40)
    assert "| router |" in chat  # Markdown is never reshaped: the chat lays the table out itself


def test_h5_close_the_cli_fits_its_output_to_the_terminal(
    data: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "44")
    assert main(["--data-dir", str(data), "module", "list"]) == 0
    out = capsys.readouterr().out
    table = out.split("\n\n", 1)[1].split("\n\nNext step:")[0]
    assert (
        max(len(line) for line in table.splitlines()) <= 44 and "  Needs: Run on a timer (schedule)" in table
    )
    monkeypatch.setenv("COLUMNS", "200")
    assert main(["--data-dir", str(data), "module", "list"]) == 0
    assert capsys.readouterr().out.split("\n\n")[1].startswith("Module ")


# Q-SY-H5-CLOSE-1 (2): the chat command also takes command-line style arguments -----------------------------


def test_h5_close_chat_accepts_command_line_style_arguments(data: Path) -> None:
    with Core(data_dir=data, hosting=True) as core:
        adapter = _adapter(core)
        plain = adapter.command("report show kind=health")
        assert plain.startswith("**Health report:")
        assert adapter.command("report show --kind health") == plain
        assert adapter.command("report show --kind=health") == plain
        assert adapter.command("module list --json") == adapter.command("module list json=true")
        assert not adapter.command("module grant ext --capability schedule").startswith("error")
        assert "schedule" in json.loads(adapter.command("module show ext json=true"))["granted"]


def test_h5_close_chat_flags_keep_their_meaning_and_say_what_is_missing(data: Path) -> None:
    with Core(data_dir=data, hosting=True) as core:
        adapter = _adapter(core)
        assert (
            adapter.command("report show --kind")
            == "error: --kind needs a value (--kind VALUE or kind=VALUE)"
        )
        # a yes/no flag never swallows the word after it
        kept = adapter.command("module remove --keep-data ext")
        assert not kept.startswith("error: expected") and "ext" not in [
            m["id"] for m in core.run("module", "list", {}, actor="cli")
        ]
        assert adapter.command("module list --nonsense x").startswith("error:")
