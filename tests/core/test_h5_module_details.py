"""H5 WP3 (#206, #210): what the Modules view needs to know about a module: its description, where it
comes from, its links and whether an update is known. Nothing here contacts the network.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sy_testing import write_module

from hermes_signalbox import labels, present
from hermes_signalbox.core import Core
from hermes_signalbox.errors import SignalboxError
from hermes_signalbox.hermes.dashboard import module_rows
from hermes_signalbox.manifest import ManifestError, load_manifest

SHA_A, SHA_B = "a" * 40, "b" * 40
GIT = f'\n[update]\nsource = "git"\nurl = "https://example.com/acme/ext.git"\nref = "{SHA_A}"\n'


def _with_module_lines(directory: Path, lines: str) -> Path:
    """Add keys to the ``[module]`` table of a test manifest."""
    path = directory / "module.toml"
    text = path.read_text(encoding="utf-8")
    assert text.count('summary = "test"\n') == 1
    path.write_text(text.replace('summary = "test"\n', 'summary = "test"\n' + lines), encoding="utf-8")
    return path


class NoNetwork:
    """A fetcher that fails the test if anything asks the network."""

    def latest(self, url: str, channel: str) -> str:
        raise AssertionError("the dashboard must never trigger a fetch")

    def fetch(self, url: str, ref: str, dest: Path) -> None:
        raise AssertionError("the dashboard must never trigger a fetch")


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    data = tmp_path / "data"
    write_module(data / "modules", "bun", isolation="subprocess", request=("schedule",))
    ext = write_module(data / "modules", "ext", isolation="subprocess")
    (ext / "module.toml").write_text(
        (ext / "module.toml").read_text(encoding="utf-8") + GIT, encoding="utf-8"
    )
    _with_module_lines(
        ext,
        'homepage = "https://example.com/acme/ext"\ndocs = "https://docs.example.com/ext/guide"\n'
        'based_on = [{name = "upstream", url = "https://example.org/upstream", license = "MIT"}]\n',
    )
    with Core(data_dir=data, hosting=True, fetcher=NoNetwork()) as c:  # type: ignore[arg-type]
        yield c


# manifest: optional links, https only ------------------------------------------------------------------


def test_h5_wp3_manifest_links_are_optional_and_loaded(tmp_path: Path) -> None:
    plain = load_manifest(write_module(tmp_path, "plain") / "module.toml")
    assert (plain.homepage, plain.docs, plain.based_on) == (None, None, ())
    path = _with_module_lines(
        write_module(tmp_path, "linked"),
        'homepage = "https://example.com/a"\ndocs = "https://example.com/a/docs?x=1#top"\n'
        'based_on = [{name = "up", url = "https://example.org/up", license = "MIT"}]\n',
    )
    linked = load_manifest(path)
    assert linked.homepage == "https://example.com/a"
    assert linked.docs == "https://example.com/a/docs?x=1#top"
    assert [dict(b) for b in linked.based_on] == [
        {"name": "up", "url": "https://example.org/up", "license": "MIT"}
    ]


@pytest.mark.parametrize(
    "lines",
    [
        'homepage = "http://example.com/a"\n',
        'homepage = "javascript:alert(1)"\n',
        'homepage = "data:text/html,x"\n',
        'homepage = "//example.com/a"\n',
        'homepage = "https://user:pw@example.com/a"\n',
        'homepage = "https://example.com/a b"\n',
        'homepage = "https://example.com/\\"><script>"\n',
        'docs = "HTTPS://example.com/a"\n',
        'docs = "https://"\n',
        'based_on = [{name = "up", url = "http://example.org/up"}]\n',
        'based_on = [{name = "up", url = "https://example.org/up", onclick = "x"}]\n',
        'based_on = [{url = "https://example.org/up"}]\n',
    ],
)
def test_h5_wp3_a_link_that_is_not_plain_https_fails_the_manifest(tmp_path: Path, lines: str) -> None:
    path = _with_module_lines(write_module(tmp_path, "hostile"), lines)
    with pytest.raises(ManifestError) as refused:
        load_manifest(path)
    message = str(refused.value)
    # refused for the link itself, not because the key is unknown to the schema
    assert "$.module: unknown key" not in message
    assert any(f"$.module.{key}" in message for key in ("homepage", "docs", "based_on"))


# module show: source, links and update state, without a fetch ---------------------------------------------


def test_h5_wp3_show_says_where_a_bundled_style_module_comes_from(core: Core) -> None:
    shown = core.run("module", "show", {"id": "bun"}, actor="api")
    assert shown["source"] == {"kind": "bundled"}
    assert shown["update"] == {"state": "bundled"}
    assert shown["links"] == {} and shown["based_on"] == []


def test_h5_wp3_show_for_a_git_module_never_fetches_and_reports_not_checked(core: Core) -> None:
    shown = core.run("module", "show", {"id": "ext"}, actor="api")  # NoNetwork would fail the test
    assert shown["source"] == {
        "kind": "git", "url": "https://example.com/acme/ext.git", "ref": SHA_A, "channel": "main",
    }  # fmt: skip
    assert shown["update"] == {"state": "not_checked", "installed": SHA_A}
    assert shown["links"] == {
        "homepage": "https://example.com/acme/ext", "docs": "https://docs.example.com/ext/guide",
    }  # fmt: skip
    assert shown["based_on"] == [
        {"name": "upstream", "url": "https://example.org/upstream", "license": "MIT"}
    ]


@pytest.mark.parametrize(
    ("available", "state"), [(SHA_B, "available"), (SHA_A, "up_to_date"), (None, "check_failed")]
)
def test_h5_wp3_show_reports_the_last_check_result(core: Core, available: str | None, state: str) -> None:
    row: dict[str, Any] = {"id": "ext", "channel": "main", "installed": SHA_A}
    row.update(
        {"error": "boom"} if available is None else {"available": available, "update": available != SHA_A}
    )
    core.updates._last_check = (time.monotonic() - 600, [row])
    update = core.run("module", "show", {"id": "ext"}, actor="api")["update"]
    assert update["state"] == state and update["installed"] == SHA_A
    assert update["checked_minutes_ago"] == 10
    assert update.get("available") == (available if state == "available" else None)


def test_h5_wp3_update_state_in_plain_words() -> None:
    assert labels.update_state({"state": "bundled"}) == "Updates with Signalbox"
    assert labels.update_state({"state": "not_checked", "installed": SHA_A}) == (
        "Not checked: start the updates module to check"
    )
    assert (
        labels.update_state({"state": "up_to_date", "checked_minutes_ago": 5})
        == "Up to date (checked 5 min ago)"
    )
    assert (
        labels.update_state(
            {"state": "available", "installed": SHA_A, "available": SHA_B, "checked_minutes_ago": 0}
        )
        == "Update available: aaaaaaa → bbbbbbb (checked just now)"
    )
    assert labels.update_state({"state": "check_failed", "checked_minutes_ago": 90}) == (
        "The last check failed (checked 90 min ago)"
    )
    assert labels.update_state({}) == "Unknown"


def test_h5_wp3_chat_and_cli_show_the_source_and_update_lines(core: Core) -> None:
    text = present.render("module", "show", core.run("module", "show", {"id": "ext"}, actor="cli"))
    assert r"- Source: git, https\://example.com/acme/ext.git at `aaaaaaa` (channel main)" in text
    assert "- Update: Not checked: start the updates module to check" in text
    assert r"- Homepage: https\://example.com/acme/ext" in text  # an address in chat is words, not a link
    assert r"- Based on: upstream (MIT, https\://example.org/upstream)" in text
    bundled = present.render("module", "show", core.run("module", "show", {"id": "bun"}, actor="cli"))
    assert "- Source: bundled with Signalbox" in bundled and "- Update: Updates with Signalbox" in bundled


# the dashboard rows -----------------------------------------------------------------------------------


def test_h5_wp3_dashboard_rows_carry_description_version_source_and_update(core: Core) -> None:
    calls: list[tuple[str, str]] = []

    def show(module_id: str) -> Any:
        calls.append(("show", module_id))
        return core.run("module", "show", {"id": module_id}, actor="api")

    def health(module_id: str) -> Any:
        calls.append(("health", module_id))
        return core.run("module", "health", {"id": module_id}, actor="api")

    rows = {r["id"]: r for r in module_rows(core.run("module", "list", {}, actor="api"), show, health)}
    assert set(rows) == {"bun", "ext"}
    assert rows["ext"]["summary"] == "test" and rows["ext"]["version"] == "0.1.0"
    assert rows["ext"]["source"]["kind"] == "git" and rows["bun"]["source"] == {"kind": "bundled"}
    assert rows["ext"]["update_text"] == "Not checked: start the updates module to check"
    assert rows["bun"]["update_text"] == "Updates with Signalbox"
    assert rows["ext"]["links"]["homepage"] == "https://example.com/acme/ext"
    assert rows["bun"]["state"] == "Ready, needs permissions" and rows["ext"]["state"] == "Manual start"
    assert rows["bun"]["health"] == ""  # not running: no check to run
    assert sorted(calls) == [
        ("show", "bun"),
        ("show", "ext"),
    ]  # no health call for a module that is not running


def test_h5_wp3_a_show_call_that_errors_leaves_the_row_in_the_table(core: Core) -> None:
    def show(module_id: str) -> Any:
        raise SignalboxError("gone")

    rows = module_rows(core.run("module", "list", {}, actor="api"), show, lambda module_id: {"ok": True})
    assert [r["id"] for r in rows] == ["bun", "ext"]
    assert all(r["summary"] == "" and r["source"] == {} and r["update_text"] == "Unknown" for r in rows)
