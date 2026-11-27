"""Independent re-review of 1.1.0 (docs/qa/19-h5-prework.md, section 9): regression tests for what three
reviewers with no part in writing the code found, after each finding was reproduced.

R-4  Module-written text could still shape a chat reply: ``_word_`` and ``~~word~~`` emphasis, a list,
     heading or code block from text that starts a line, and bare web addresses that become links.
R-5  A deeply nested result raised ``RecursionError`` in the formatter.
R-6  The failure line the command line prints on stderr carried module-written text as it came (the R-1
     class, on the one path R-1 did not cover); a subprocess module chose its own error type name.
R-7  The first-start copy: an old directory that is itself a link was followed; the copy ran again when the
     new state was lost, bringing back grants revoked since; a damaged ``state.db`` was copied unchecked;
     an operating-system error escaped as a traceback; copied files kept their old permission bits.
R-8  ``--data-dir`` and ``api serve --port`` given twice kept the last value silently.
R-9  The dashboard received module-written text with control and direction-override characters in it; the
     R-1 filter covered chat and terminal only.
R-10 The inbox took the name of the module a notice is "from" out of the event's own data, so a module
     could post a notice that named another one.
R-11 The dashboard's start-mode route read a body of any size and any content type; a list where the API
     expects a module id dropped the connection.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from hermes_signalbox import cli, legacy, present, rpc
from hermes_signalbox.api import ControlServer
from hermes_signalbox.core import Core
from hermes_signalbox.errors import ConfigError
from hermes_signalbox.hermes import dashboard

ESC = "\x1b"
MD, TEXT = present.MARKDOWN, present.TEXT


def _md(text: str) -> str:
    return str(present._safe_text(text, True))


# --- R-4 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("_italic_ and __bold__", r"\_italic\_ and \_\_bold\_\_"),
        ("~~struck~~", r"\~\~struck\~\~"),
        ("- item", r"\- item"),
        ("+ item", r"\+ item"),
        ("1. first", r"1\. first"),
        ("12) twelfth", r"12\) twelfth"),
        ("---", r"\---"),
        ("===", r"\==="),
        ("    code block", "code block"),
        ("see https://evil.example/x", r"see https\://evil.example/x"),
        ("go to www.evil.example now", r"go to www\.evil.example now"),
        ("mail me@evil.example", r"mail me\@evil.example"),
    ],
)
def test_h5_r4_module_text_cannot_start_a_markdown_construct(text: str, shown: str) -> None:
    assert _md(text) == shown


@pytest.mark.parametrize(
    "text",
    ["missing_grants", "check_failed", "up_to_date", "1.0.0", "-1", "2026-11-27T09:00:00+00:00", "a-b"],
)
def test_h5_r4_identifiers_versions_and_times_are_left_alone(text: str) -> None:
    assert _md(text) == text
    assert present._safe({text: text}, True) == {text: text}  # keys stay usable for look-ups


def test_h5_r4_text_style_is_not_escaped() -> None:
    assert present._safe_text("_x_ ~~y~~ - z https://a.example", False) == "_x_ ~~y~~ - z https://a.example"


def test_h5_r4_a_summary_cannot_become_a_list_heading_or_link_in_module_show() -> None:
    for hostile in ("- item", "1. first", "---", "===", "    code", "see https://evil.example", "_x_"):
        row = {"id": "evil", "version": "1", "status": "failed", "mode": "auto", "missing_grants": [],
               "error": hostile, "requested": [], "granted": [], "isolation": "subprocess",
               "license": hostile, "state": "Error"}  # fmt: skip
        out = present.render("module", "show", row, style=MD, summaries={"evil": hostile}, subject="evil")
        assert hostile not in out.splitlines(), hostile  # never a line of its own, as written
        assert "https://" not in out and "_x_" not in out.replace(r"\_x\_", "")


# --- R-5 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("style", [MD, TEXT])
def test_h5_r5_a_deeply_nested_result_is_cut_off_not_a_crash(style: str) -> None:
    deep: dict[str, object] = {}
    cursor = deep
    for _ in range(3000):
        cursor["a"] = {}
        cursor = cursor["a"]  # type: ignore[assignment]
    out = present.render("module", "action", deep, style=style, subject="evil")
    assert "nested too deeply" in out
    wide = [[[[["x"]]]]] * 3
    assert present.render("module", "action", {"items": wide}, style=style, subject="evil")


# --- R-6 ------------------------------------------------------------------------------------------------


def test_h5_r6_the_failure_line_on_stderr_carries_no_control_characters() -> None:
    hostile = f"down{ESC}]52;c;ZXZpbA=={ESC}\\ {ESC}[2K\rgone\u202e"
    for result in ({"ok": False, "detail": hostile}, {"status": "failed", "id": "evil", "error": hostile},
                   {"ok": False, "reason": hostile}):  # fmt: skip
        line = cli._failure(result)
        assert line is not None and "down" in line
        assert ESC not in line and "\r" not in line and "\u202e" not in line


def test_h5_r6_a_subprocess_module_cannot_choose_its_error_type_name() -> None:
    assert rpc.remote_type_name("ValueError") == "ValueError"
    assert rpc.remote_type_name("my_module.Oops") == "Error"
    for hostile in (f"{ESC}[31mBoom", "Boom\nline", "a" * 65, "", 5, None, "Sp ace"):
        assert rpc.remote_type_name(hostile) == "Error"


def test_h5_r6_a_time_out_of_range_is_shown_as_written() -> None:
    assert (
        present._when("0001-01-01T00:00:00+00:00", timezone(timedelta(hours=-5)))
        == "0001-01-01T00:00:00+00:00"
    )


# --- R-7 ------------------------------------------------------------------------------------------------


def _link(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))  # needs no privilege, unlike a symlink
    else:
        os.symlink(target, link, target_is_directory=True)


def _old_install(directory: Path) -> None:
    with Core(data_dir=directory) as core:
        core.audit.append(
            actor="cli", action="policy.granted", module="router", detail={"capability": "ui.panel"}
        )


def test_h5_r7_an_old_directory_that_is_itself_a_link_is_not_a_candidate_and_is_refused(
    tmp_path: Path,
) -> None:
    real = tmp_path / "elsewhere"
    _old_install(real)
    (real / "host.lock").unlink(missing_ok=True)
    data = tmp_path / "data"
    data.mkdir()
    old, new = data / legacy.LEGACY_NAME, data / "signalbox"
    _link(real, old)
    assert legacy.legacy_candidates(new, hermes=False) == []
    with pytest.raises(ConfigError, match="link"):
        legacy.migrate_data_dir(new, [old])
    assert not new.exists() and not (real / "host.lock").exists()


def test_h5_r7_the_copy_happens_once_even_if_the_new_state_is_lost(tmp_path: Path) -> None:
    old, new = tmp_path / legacy.LEGACY_NAME, tmp_path / "signalbox"
    _old_install(old)
    assert legacy.migrate_data_dir(new, legacy.legacy_candidates(new, hermes=False)) is not None
    marker = old / legacy.MARKER
    assert marker.is_file() and "signalbox" in marker.read_text(encoding="utf-8")
    assert not (new / legacy.MARKER).exists()
    shutil.rmtree(new)  # a reset, a reinstall, a damaged disk
    assert legacy.legacy_candidates(new, hermes=False) == []
    assert legacy.migrate_data_dir(new, legacy.legacy_candidates(new, hermes=False)) is None
    assert not new.exists()  # the 1.0 grants did not come back
    marker.unlink()  # the documented way to copy again on purpose
    assert legacy.migrate_data_dir(new, legacy.legacy_candidates(new, hermes=False)) is not None


def test_h5_r7_a_damaged_state_file_is_refused_and_nothing_is_copied(tmp_path: Path) -> None:
    old, new = tmp_path / legacy.LEGACY_NAME, tmp_path / "signalbox"
    _old_install(old)
    for extra in ("state.db-wal", "state.db-shm"):
        (old / extra).unlink(missing_ok=True)
    (old / "state.db").write_bytes(b"this is not a database" * 400)
    with pytest.raises(ConfigError, match=r"state\.db") as caught:
        legacy.migrate_data_dir(new, [old])
    assert "nothing was copied" in str(caught.value)
    assert not new.exists() and not (old / legacy.MARKER).exists()


def test_h5_r7_an_operating_system_error_is_a_clear_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, new = tmp_path / legacy.LEGACY_NAME, tmp_path / "signalbox"
    _old_install(old)

    def denied(*_a: object, **_k: object) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(legacy.shutil, "copytree", denied)
    with pytest.raises(ConfigError, match="nothing was copied"):
        legacy.migrate_data_dir(new, [old])
    assert not new.exists() and not new.with_name(new.name + ".migrating").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits are a POSIX matter")
def test_h5_r7_copied_files_are_private_to_the_owner(tmp_path: Path) -> None:
    old, new = tmp_path / legacy.LEGACY_NAME, tmp_path / "signalbox"
    _old_install(old)
    backups = old / "hermes-config-backups"
    backups.mkdir()
    (backups / "config.yaml").write_text("x", encoding="utf-8")
    os.chmod(backups, 0o755)  # noqa: S103 - the loose mode under test
    os.chmod(backups / "config.yaml", 0o644)
    assert legacy.migrate_data_dir(new, [old]) is not None
    assert stat.S_IMODE((new / "hermes-config-backups").stat().st_mode) == 0o700
    assert stat.S_IMODE((new / "hermes-config-backups" / "config.yaml").stat().st_mode) == 0o600


# --- R-8 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--data-dir", "a", "--data-dir", "b", "module", "list"],
        ["api", "serve", "--port", "1", "--port", "2"],
    ],
)
def test_h5_r8_global_options_given_twice_are_refused(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(argv)
    assert "more than once" in capsys.readouterr().err


# --- R-9 ------------------------------------------------------------------------------------------------

DIRTY = f"up\u202eside{ESC}[2Kdown\u200b\x07"


def _has_control(value: object) -> bool:
    if isinstance(value, str):
        return any(ch in value for ch in ("\u202e", ESC, "\u200b", "\x07"))
    if isinstance(value, dict):
        return any(_has_control(k) or _has_control(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return any(_has_control(v) for v in value)
    return False


def test_h5_r9_the_dashboard_gets_module_text_without_control_characters() -> None:
    row = {"id": "evil", "status": "active", "mode": "auto", "missing_grants": [], "version": "1"}
    shown = {
        "summary": DIRTY,
        "license": DIRTY,
        "source": {"kind": "git", "url": DIRTY, "ref": DIRTY},
        "links": {"docs": DIRTY},
        "based_on": [{"name": DIRTY, "url": DIRTY}],
        "update": {"state": "bundled"},
    }
    rows = dashboard.module_rows([row], lambda _id: shown, lambda _id: {"ok": False, "detail": DIRTY})
    assert rows and rows[0]["summary"].startswith("upside") and not _has_control(rows)
    item = {
        "id": "a" * 16,
        "ts": "2026-11-27T09:00:00+00:00",
        "type": "evil.note",
        "module": DIRTY,
        "severity": "info",
        "title": DIRTY,
        "detail": f"k={DIRTY}",
        "state": "open",
    }
    inbox = dashboard.inbox_view({"items": [item]})
    assert inbox["items"] and not _has_control(inbox)
    report = dashboard.report_view({"kind": "usage", "summary": {"headline": DIRTY, "lines": [DIRTY]},
                                    "modules": {"evil": {"note": DIRTY}}})  # fmt: skip
    assert not _has_control(report)


# --- R-11 -----------------------------------------------------------------------------------------------


def test_h5_r11_a_list_where_a_module_id_belongs_is_not_served(tmp_path: Path) -> None:
    with Core(data_dir=tmp_path / "data") as core:
        server = ControlServer(core, profile="dashboard")
        assert server.actor_for("module", "action", {"id": ["inbox"], "action": "list"}) == "hermes"
        assert server.actor_for("module", "action", {"id": "inbox", "action": ["ack"]}) == "hermes"
        assert server.actor_for("module", "action", {"id": "inbox", "action": "list"}) == "api"
