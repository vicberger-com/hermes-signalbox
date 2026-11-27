"""H5 WP3 (#206, #208, #210): the Modules view of the dashboard tab.

``dashboard/dist/index.js`` is plain JS with no build step, so it is tested by running the real file under
Node with stand-ins for the Hermes plugin SDK and React (``tests/fixtures/dashboard_harness.js``): the view
is rendered from known rows and the resulting element tree is checked.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from hermes_signalbox import labels

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "dashboard" / "dist" / "index.js"
HARNESS = ROOT / "tests" / "fixtures" / "dashboard_harness.js"
MODULES = "/api/plugins/signalbox/modules"
GIT_URL = "https://example.com/acme/ext.git"


def _node() -> str:
    found = os.environ.get("SIGNALBOX_NODE") or shutil.which("node")
    if not found:  # a workstation where Node only ships inside the Hermes desktop app
        local = os.environ.get("LOCALAPPDATA", "")
        bundled = (
            sorted(glob.glob(os.path.join(local, "hermes", "tools", "node-*", "node.exe"))) if local else []
        )
        found = bundled[-1] if bundled else None
    if not found:
        pytest.skip("Node.js is not installed")
    return found


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
    done = subprocess.run(  # noqa: S603 - a fixed harness file, run with the located node
        [_node(), str(HARNESS), str(INDEX)],
        input=json.dumps(scenario), capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-2000:]
    out: dict[str, Any] = json.loads(done.stdout)
    return out


def _all(node: Any, test: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for child in node:
            found += _all(child, test)
    elif isinstance(node, dict):
        if test(node):
            found.append(node)
        found += _all(node["children"], test)
    return found


def _text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_text(c) for c in node)
    return _text(node["children"]) if isinstance(node, dict) else ""


def _by(tree: Any, marker: str) -> dict[str, Any]:
    [hit] = _all(tree, lambda n: n["props"].get("data-sy") == marker)
    return hit


def test_h5_wp3_the_tab_still_registers_and_shows_every_column() -> None:
    out = _run()
    assert out["registered"] == ["signalbox"]
    headers = [
        _text(th)
        for th in _all(out["tree"], lambda n: n["type"] == "th" and n["props"].get("scope") == "col")
    ]
    assert headers == ["Module", "State", "Start mode", "Health", "Version", "Source", "Update", "Action"]
    row = _by(out["tree"], "row-meter")
    text = _text(row)
    assert "What meter does." in text and "0.1.0" in text and "Updates with Signalbox" in text
    assert "Bundled with Signalbox" in text and "Running" in text
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
    assert stop["props"].get("aria-disabled") != "true" and _text(stop) == "Stop meter"
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
