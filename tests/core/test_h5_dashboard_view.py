"""H5 WP3 (#206, #208, #210): the Modules view of the dashboard tab.

``dashboard/dist/index.js`` is plain JS with no build step, so it is tested by running the real file under
Node with stand-ins for the Hermes plugin SDK and React (``tests/fixtures/dashboard_harness.js``): the view
is rendered from known rows and the resulting element tree is checked.
"""

from __future__ import annotations

import json
from typing import Any

from sy_dashboard import BASE, INDEX, ROOT, render
from sy_dashboard import by_marker as _by
from sy_dashboard import find_all as _all
from sy_dashboard import markers as _markers
from sy_dashboard import text_of as _text

from hermes_signalbox import labels

MODULES = BASE + "/modules"
GIT_URL = "https://example.com/acme/ext.git"


def _row(mid: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": mid, "version": "0.1.0", "status": "verified", "mode": "auto", "isolation": "in-process",
        "error": None, "requested": [], "granted": [], "missing_grants": [], "health": "",
        "summary": f"What {mid} does.", "license": "Apache-2.0", "source": {"kind": "bundled"}, "links": {},
        "based_on": [], "update": {"state": "bundled"}, "update_text": "Updates with Signalbox",
        "state": "Ready, starts with Hermes",
    }  # fmt: skip
    row.update(over)
    return row


ROWS = [
    _row("meter", status="active", state="Running", health="ok"),
    _row("router", missing_grants=["hermes.hooks", "ui.panel"], requested=["hermes.hooks", "ui.panel"],
         state="Ready, needs permissions"),
    _row("scanner", mode="disabled", state="Disabled"),
    _row("ext", mode="manual", state="Manual start",
         source={"kind": "git", "url": GIT_URL, "ref": "a" * 40, "channel": "main"},
         links={"homepage": "https://example.com/acme/ext", "docs": "javascript:alert(1)"},
         based_on=[{"name": "up<b>", "url": "https://example.org/up", "license": "MIT"},
                   {"name": "bad", "url": "http://example.org/plain"}],
         update={"state": "available"}, update_text="Update available: aaaaaaa to bbbbbbb"),
]  # fmt: skip


def _run(**scenario: Any) -> dict[str, Any]:
    scenario.setdefault("rows", ROWS)
    scenario.setdefault("labels", labels.glossary())
    scenario.setdefault(
        "state",
        [
            {"loading": False, "data": scenario["rows"], "error": None},
            {"loading": False, "data": scenario["labels"], "error": None},
        ],
    )
    return render(**scenario)


def test_h5_wp3_the_tab_still_registers_and_shows_every_column() -> None:
    out = _run()
    assert out["registered"] == ["signalbox"]
    headers = [
        _text(th)
        for th in _all(out["tree"], lambda n: n["type"] == "th" and n["props"].get("scope") == "col")
    ]
    assert headers == ["Module", "State", "Start mode", "Version", "Action"]
    row = _by(out["tree"], "row-meter")
    text = _text(row)
    assert "What meter does." in text and "0.1.0" in text and "Running" in text
    assert "Bundled and updated with Signalbox" in text
    for raw in ("verified", "missing_grants", "in-process", "null", "undefined"):
        assert raw not in _text(out["tree"]), raw


def test_h5_wp3_a_module_that_lacks_grants_has_a_disabled_button_with_the_reason_and_command() -> None:
    out = _run(clicks=[{"target": "action-router"}])
    button = _by(out["tree"], "action-router")
    assert button["props"]["aria-disabled"] == "true"
    reason = _by(out["tree"], "reason-router")
    assert button["props"]["aria-describedby"] == reason["props"]["id"]
    text = _text(reason)
    assert "Watch and steer Hermes requests" in text and "Show a dashboard panel" in text
    assert "hermes signalbox module grant router --capability hermes.hooks" in text
    assert out["clicks"][0]["fetches"] == []  # a disabled button sends nothing


def test_h5_wp3_a_disabled_module_says_how_to_enable_it_and_running_ones_can_be_stopped() -> None:
    out = _run(clicks=[{"target": "action-meter"}])
    assert _by(out["tree"], "action-scanner")["props"]["aria-disabled"] == "true"
    assert "start mode" in _text(_by(out["tree"], "reason-scanner")).lower()
    stop = _by(out["tree"], "action-meter")
    assert stop["props"].get("aria-disabled") != "true" and _text(stop) == "Stop"
    assert stop["props"]["aria-label"] == "Stop meter"
    assert out["clicks"][0]["fetches"] == [[MODULES + "/meter/deactivate", {"method": "POST"}]]
    assert out["refreshed"] == 1


def test_h5_wp3_a_refused_action_shows_the_cores_message_on_the_row() -> None:
    message = "Can't start: not granted schedule"
    out = _run(clicks=[{"target": "action-ext"}], failures={MODULES + "/ext/activate": message})
    [click] = out["clicks"]
    assert click["fetches"] == [[MODULES + "/ext/activate", {"method": "POST"}]]
    assert any(isinstance(value, dict) and value.get("ext") == message for _index, value in click["sets"])
    assert out.get("refreshed") is None  # the error is kept on screen, not wiped by a silent refresh
    shown = _run(state=[
        {"loading": False, "data": ROWS, "error": None},
        {"loading": False, "data": labels.glossary(), "error": None},
        {"ext": message},
    ])  # fmt: skip
    alert = _by(shown["tree"], "error-ext")
    assert alert["props"]["role"] == "alert" and message in _text(alert)


def test_h5_wp3_mode_is_set_with_a_post_and_its_options_are_labelled() -> None:
    out = _run(clicks=[{"target": "mode-ext", "event": "onChange", "arg": {"target": {"value": "auto"}}}])
    select = _by(out["tree"], "mode-ext")
    assert select["type"] == "select" and select["props"]["value"] == "manual"
    assert select["props"]["aria-label"] == "Start mode for ext"
    options = {o["props"]["value"]: _text(o) for o in _all(select, lambda n: n["type"] == "option")}
    assert options == {"auto": "Starts with Hermes", "manual": "Manual start", "disabled": "Disabled"}
    [[url, sent]] = out["clicks"][0]["fetches"]
    assert url == MODULES + "/ext/mode" and sent["method"] == "POST"
    assert json.loads(sent["body"]) == {"mode": "auto"}
    assert sent["headers"]["Content-Type"] == "application/json"


def test_h5_wp3_only_https_links_are_rendered_with_the_host_and_safe_attributes() -> None:
    urls = [
        "https://example.com/a", "http://example.com/a", "javascript:alert(1)", "//example.com/a",
        "https://user:pw@example.com/a", 'https://example.com/"><script>', "https://example.com/a b", "",
    ]  # fmt: skip
    out = _run(urls=urls)
    assert out["safe"] == {u: (u if u == "https://example.com/a" else None) for u in urls}
    assert out["hosts"]["https://example.com/a"] == "example.com"
    links = _all(_by(out["tree"], "row-ext"), lambda n: n["type"] == "a")
    assert sorted(a["props"]["href"] for a in links) == [
        "https://example.com/acme/ext", "https://example.com/acme/ext", "https://example.org/up",
    ]  # fmt: skip
    for a in links:
        assert a["props"]["rel"] == "noopener noreferrer" and a["props"]["target"] == "_blank"
        assert "dangerouslySetInnerHTML" not in a["props"]
    assert any("up<b> (example.org)" in _text(a) for a in links)  # text, never markup; the host is shown
    assert "javascript:" not in json.dumps(out["tree"]) and "http://example.org/plain" not in json.dumps(
        out["tree"]
    )


def test_h5_wp3_terms_have_keyboard_tooltips_and_a_legend_from_the_labels() -> None:
    out = _run()
    term = _by(out["tree"], "state-router")
    assert term["props"]["tabIndex"] == 0 and term["props"]["onKeyDown"] == "[function]"
    [tip] = _all(term, lambda n: n["props"].get("role") == "tooltip")
    assert term["props"]["aria-describedby"] == tip["props"]["id"]
    assert labels.STATUSES["verified"].meaning in _text(tip)
    legend = _text(_by(out["tree"], "legend"))
    for table in (labels.STATUSES, labels.MODES):
        for entry in table.values():
            assert entry.label in legend and entry.meaning in legend
    assert _by(out["tree"], "live")["props"]["aria-live"] == "polite"


def test_h5_wp3_the_view_says_so_while_loading_and_when_the_api_is_off() -> None:
    loading = _run(state=[{"loading": True, "data": None, "error": None}])
    assert "Loading modules" in _text(loading["tree"])
    failed = _run(state=[{"loading": False, "data": None, "error": "Signalbox API is off"}])
    assert "Could not load modules: Signalbox API is off" in _text(failed["tree"])


def test_h5_wp3_no_action_in_the_modules_view_discards_a_failure() -> None:
    js = INDEX.read_text(encoding="utf-8")
    view = js[js.index("// --- Modules view") : js.index("// --- Inbox view")]
    assert "props.refresh, props.refresh" not in view
    assert "innerHTML" not in js and "eval(" not in js


# --- The view on an ordinary display (usability review of the 1.1.0 release candidate) ----------------------
# Usability review of the 1.1.0 release candidate: the Modules view on an ordinary display.
#
# At 1366 pixels the eight-column table showed three modules of twelve: Source and Update said the same thing
# on every row and forced every other cell to wrap. Where a module comes from, how it updates, its licence,
# its permissions and its links now sit behind one "About" control beside the module's name; what differs
# from the ordinary case (installed from git, an update available, a health problem) stays visible.

STYLE = ROOT / "dashboard" / "dist" / "style.css"


def test_h5_about_is_a_real_button_that_opens_by_click_keyboard_and_pointer() -> None:
    out = _run(clicks=[{"target": "about-meter"}])
    about = _by(out["tree"], "about-meter")
    assert about["type"] == "button" and about["props"]["type"] == "button"
    assert about["props"]["aria-label"] == "About meter"
    assert about["props"]["aria-expanded"] == "false"
    panel = _by(out["tree"], "about-panel-meter")
    assert about["props"]["aria-controls"] == panel["props"]["id"]
    assert any(value == "open" for _index, value in out["clicks"][0]["sets"])  # a click or tap opens it
    wrapper = _by(out["tree"], "about-wrap-meter")
    assert wrapper["props"]["onKeyDown"] == "[function]"  # Esc closes it
    css = STYLE.read_text(encoding="utf-8")
    assert ".sy-about:hover > .sy-about-panel" in css and ".sy-about:focus-within > .sy-about-panel" in css


def test_h5_about_tells_the_whole_story_of_a_bundled_module() -> None:
    asked, given = ["hermes.hooks", "llm.paid", "ui.panel"], ["hermes.hooks", "ui.panel"]
    rows = [_row("meter", status="active", state="Running", health="ok", requested=asked, granted=given)]
    text = _text(_by(_run(rows=rows)["tree"], "about-panel-meter"))
    assert "Bundled and updated with Signalbox" in text
    assert "Apache-2.0" in text and "inside the Signalbox process" in text
    assert "Watch and steer Hermes requests" in text and "Show a dashboard panel" in text  # granted, in words
    assert "Not granted" in text and "Use paid models" in text  # asked for, not granted
    assert "in-process" not in text and "hermes.hooks" not in text


def test_h5_about_of_a_git_module_names_the_commit_the_update_state_and_keeps_the_links() -> None:
    panel = _by(_run()["tree"], "about-panel-ext")
    text = _text(panel)
    assert "aaaaaaa" in text and "channel main" in text
    assert "Update available: aaaaaaa to bbbbbbb" in text
    assert len(_all(panel, lambda n: n["type"] == "a")) == 3


def test_h5_what_differs_from_the_ordinary_case_is_visible_without_opening_anything() -> None:
    out = _run()
    assert _text(_by(out["tree"], "tag-git-ext")) == "From git"
    assert _text(_by(out["tree"], "tag-update-ext")) == "Update available"
    assert _markers(_by(out["tree"], "row-meter"), "tag-") == []
    row = _row("ext", source={"kind": "git", "url": "", "ref": "a" * 40}, update={"state": "check_failed"})
    failed = _run(rows=[row])
    assert _text(_by(failed["tree"], "tag-update-ext")) == "Update check failed"


def test_h5_state_says_whether_it_runs_and_never_repeats_the_start_mode() -> None:
    rows: list[dict[str, Any]] = [
        *ROWS,
        _row("sick", status="active", state="Running", health="degraded: no route"),
        _row("broken", status="failed", state="Error", error="import failed"),
    ]
    tree = _run(rows=rows)["tree"]
    shown = {
        m: _text(_by(tree, "state-" + m)) for m in ("meter", "router", "scanner", "ext", "sick", "broken")
    }
    for mid, start in (("meter", "Running"), ("router", "Needs permissions"), ("scanner", "Not running"),
                       ("ext", "Not running"), ("sick", "Running"), ("broken", "Error")):  # fmt: skip
        assert shown[mid].startswith(start), (mid, shown[mid])
    assert "degraded: no route" in _text(_by(tree, "health-sick"))
    assert _markers(_by(tree, "row-meter"), "health-") == []  # a healthy module adds nothing
    assert "import failed" in _text(_by(tree, "row-broken"))


def test_h5_a_summary_line_counts_the_modules() -> None:
    assert (
        _text(_by(_run()["tree"], "summary"))
        == "1 of 4 modules running · 0 failed · 1 waiting for permissions"
    )


def test_h5_short_cells_do_not_wrap_and_the_start_button_names_its_module_for_a_screen_reader() -> None:
    out = _run()
    start = _by(out["tree"], "action-ext")
    assert _text(start) == "Start" and start["props"]["aria-label"] == "Start ext"
    css = STYLE.read_text(encoding="utf-8")
    assert ".sy-nowrap { white-space: nowrap; }" in css
    js = INDEX.read_text(encoding="utf-8")
    assert '"Source", "Update"' not in js


def test_h5_the_legend_is_folded_away_like_the_page_introduction() -> None:
    legend = _by(_run()["tree"], "legend")
    assert legend["type"] == "details" and "open" not in legend["props"]
    [summary] = _all(legend, lambda n: n["type"] == "summary")
    assert _text(summary) == "What the columns mean"
    assert not _all(legend, lambda n: n["type"] == "h2")  # the summary is its title
    css = STYLE.read_text(encoding="utf-8")
    assert ".sy-legend { margin-top: 1rem; }" in css  # clear of the table's last line


def test_h5_the_page_is_as_wide_as_its_content_needs_and_no_wider() -> None:
    css = STYLE.read_text(encoding="utf-8")
    # a table takes the width of its content, never more than the page; the page stops growing at a
    # readable width and is free to shrink below it
    assert ".sy-table { border-collapse: collapse; width: auto; max-width: 100%; }" in css
    assert "max-width: 76rem;" in css[css.index(".sy-root {") : css.index("}", css.index(".sy-root {"))]
    assert "{ width: 100%" not in css and "; width: 100%" not in css
