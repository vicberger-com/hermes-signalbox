"""H5 WP4 (#207, #208): the Reports and Inbox views, the Refresh control and the page help, checked by
rendering the real ``dashboard/dist/index.js`` under Node (see ``tests/sy_dashboard.py``).
"""

from __future__ import annotations

import json
import re
from typing import Any

from sy_dashboard import BASE, INDEX, by_marker, find_all, loaded, markers, render, text_of

from hermes_signalbox import reports
from hermes_signalbox.hermes.dashboard import inbox_view, report_view


def _rec(seq: int, action: str, module: str = "router", actor: str = "cli", **detail: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "ts": f"2026-11-25T20:{seq:02d}:00.000000+00:00",
        "actor": actor,
        "action": action,
        "module": module,
        "detail": detail,
        "prev": "p" * 8,
        "hash": "h" * 8,
    }


def _report(kind: str, **payload: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind, **payload}
    out.update(purpose=reports.PURPOSES[kind], summary=reports.summarize(out, modules=payload.get("modules")))
    out["view"] = report_view(out)
    return out


def _module(mid: str, status: str, missing: tuple[str, ...] = (), error: str | None = None) -> dict[str, Any]:
    return {
        "id": mid,
        "version": "0.1.0",
        "status": status,
        "mode": "auto",
        "error": error,
        "missing_grants": list(missing),
    }


HEALTH = _report(
    "health",
    modules=[_module("meter", "active"), _module("router", "verified", ("hermes.hooks",))],
    failed=[],
)
SECURITY_BAD = _report(
    "security",
    audit={"ok": False, "records": 6, "first_bad_seq": 7, "reason": "hash mismatch"},
    recent_denials=[_rec(i, "policy.denied", actor="core", capability="hermes.hooks") for i in (1, 2)],
)
CHANGES = _report("changes", changes=[_rec(1, "policy.granted", capability="ui.panel")])


def _item(n: int, **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": f"{n:016x}",
        "at": 1_800_000_000.0 + n,
        "module": "meter",
        "type": "meter.threshold",
        "severity": "high",
        "title": "Quota threshold reached",
        "detail": "percent=80, quota=day",
        "state": "open",
    }
    item.update(over)
    return item


INBOX = inbox_view(
    {"items": [_item(2), _item(1), _item(3, severity="info", title="Module updated", detail="")]}
)


def _reports(report: dict[str, Any], kind: str, **more: Any) -> dict[str, Any]:
    return render(view="Report", state=[kind, loaded(report)], **more)


# Reports ----------------------------------------------------------------------------------------------


def test_h5_wp4_a_report_leads_with_its_summary_and_purpose_and_hides_the_raw_json() -> None:
    tree = _reports(HEALTH, "health")["tree"]
    headline = by_marker(tree, "headline")
    assert text_of(headline) == "1 of 2 modules running · 0 failed · 1 waiting for permissions"
    assert reports.PURPOSES["health"] in text_of(by_marker(tree, "purpose"))
    assert "router is waiting for 1 permission" in text_of(by_marker(tree, "attention"))
    raw = by_marker(tree, "raw")
    assert raw["type"] == "details" and "open" not in raw["props"]  # collapsed until asked for
    outside = json.dumps(tree).replace(json.dumps(raw), "")
    for needle in ("missing_grants", '\\"kind\\"', "first_bad_seq", "hhhhhhhh"):
        assert needle not in outside, needle
    assert json.loads(text_of(find_all(raw, lambda n: n["type"] == "pre")))["kind"] == "health"
    assert "view" not in json.loads(text_of(find_all(raw, lambda n: n["type"] == "pre")))


def test_h5_wp4_the_health_report_is_a_table_with_plain_states_and_needs() -> None:
    tree = _reports(HEALTH, "health")["tree"]
    headers = [
        text_of(th) for th in find_all(tree, lambda n: n["type"] == "th" and n["props"].get("scope") == "col")
    ]
    assert headers == ["Module", "State", "Details", "Needs"]
    body = text_of(find_all(tree, lambda n: n["type"] == "tbody"))
    assert "Running" in body and "Ready, needs permissions" in body
    assert "Watch and steer Hermes requests (hermes.hooks)" in body and "verified" not in body


def test_h5_wp4_a_broken_audit_log_is_an_alert_and_refusals_are_grouped() -> None:
    tree = _reports(SECURITY_BAD, "security")["tree"]
    headline = by_marker(tree, "headline")
    assert headline["props"]["role"] == "alert" and "AUDIT LOG PROBLEM" in text_of(headline)
    body = text_of(find_all(tree, lambda n: n["type"] == "tbody"))
    assert "Permission refused" in body and "2 times" in body and "Signalbox" in body
    assert "2026-11-25T20:" not in body  # times are local and relative, never the stored form
    ok = _reports(HEALTH, "health")["tree"]
    assert by_marker(ok, "headline")["props"].get("role") != "alert"


def test_h5_wp4_changes_read_as_sentences_and_an_empty_report_says_so() -> None:
    body = text_of(_reports(CHANGES, "changes")["tree"])
    assert "CLI granted router the permission to show a dashboard panel" in body
    empty = text_of(_reports(_report("changes", changes=[]), "changes")["tree"])
    assert "No changes in the recent records" in empty
    quiet = _report(
        "security", audit={"ok": True, "records": 3, "first_bad_seq": None, "reason": ""}, recent_denials=[]
    )
    assert "Nothing was refused" in text_of(_reports(quiet, "security")["tree"])


def test_h5_wp4_the_report_selector_is_labelled_and_asks_for_the_chosen_kind() -> None:
    out = _reports(
        HEALTH,
        "health",
        clicks=[{"target": "report-kind", "event": "onChange", "arg": {"target": {"value": "usage"}}}],
    )
    select = by_marker(out["tree"], "report-kind")
    options = {o["props"]["value"]: text_of(o) for o in find_all(select, lambda n: n["type"] == "option")}
    assert options == {"health": "Health", "usage": "Usage", "security": "Security", "changes": "Changes"}
    assert [0, "usage"] in out["clicks"][0]["sets"]
    assert find_all(out["tree"], lambda n: n["type"] == "label")


def test_h5_wp4_times_are_local_with_a_relative_part() -> None:
    now = 1_800_000_000_000
    out = render(
        when=[
            [now - 180_000, now],
            [(now - 7_200_000) / 1000, now],
            ["2027-01-15T07:59:00+00:00", now],
            ["", now],
        ]
    )
    three, two_hours, iso, blank = out["when"]
    assert three.endswith("(3 min ago)") and two_hours.endswith("(2 h ago)")
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(", three)
    assert iso.endswith("ago)") and "T07:59" not in iso
    assert blank == ""


# Refresh and the page ---------------------------------------------------------------------------------


def test_h5_wp4_refresh_is_a_toolbar_button_outside_the_tabs_with_an_updated_time() -> None:
    idle = render(view="Page", state=["modules", 0, {"loading": False, "at": 1_800_000_000_000}])["tree"]
    tabs = by_marker(idle, "tabs")
    assert [n["props"]["role"] for n in find_all(tabs, lambda n: n["type"] == "button")] == [
        "tab",
        "tab",
        "tab",
    ]
    button = by_marker(idle, "refresh")
    assert not find_all(tabs, lambda n: n["props"].get("data-sy") == "refresh")
    assert text_of(button) == "Refresh" and button["props"]["aria-disabled"] == "false"
    updated = by_marker(idle, "updated")
    assert updated["props"]["aria-live"] == "polite" and re.search(
        r"Updated \d{2}:\d{2}:\d{2}", text_of(updated)
    )


def test_h5_wp4_refresh_shows_that_it_is_working_and_cannot_be_clicked_twice() -> None:
    busy = render(
        view="Page", state=["modules", 0, {"loading": True, "at": None}], clicks=[{"target": "refresh"}]
    )
    button = by_marker(busy["tree"], "refresh")
    # aria-disabled, not disabled: the button keeps keyboard focus while it works
    assert button["props"]["aria-disabled"] == "true" and "Refreshing" in text_of(button)
    assert busy["clicks"][0]["sets"] == [] and busy["clicks"][0]["fetches"] == []
    out = render(
        view="Page", state=["modules", 4, {"loading": False, "at": None}], clicks=[{"target": "refresh"}]
    )
    sets = out["clicks"][0]["sets"]
    assert [1, 5] in sets  # a new tick, so every view loads again even when nothing changed
    assert any(index == 2 and value.get("loading") is True for index, value in sets)


def test_h5_wp4_the_page_explains_itself_and_the_inbox_tab_counts_open_notices() -> None:
    page = render(view="Page", state=["inbox", 0, {"loading": False, "at": None}, loaded(INBOX)])["tree"]
    intro = text_of(by_marker(page, "intro"))
    for phrase in ("optional modules", "only what you have permitted", "Modules", "Inbox", "Reports"):
        assert phrase in intro, phrase
    assert by_marker(page, "intro")["type"] == "details"
    tab = by_marker(page, "tab-inbox")
    assert text_of(tab) == "Inbox (3 open)" and tab["props"]["aria-selected"] == "true"


# Inbox ------------------------------------------------------------------------------------------------


def test_h5_wp4_inbox_shows_time_severity_labelled_fields_and_grouped_repeats() -> None:
    tree = render(view="Inbox", state=["open", loaded(INBOX), ""])["tree"]
    assert markers(tree, "notice-") == [
        "notice-" + INBOX["groups"][0]["ids"][0],
        "notice-" + INBOX["groups"][1]["ids"][0],
    ]
    first = by_marker(tree, "notice-" + INBOX["groups"][0]["ids"][0])
    text = text_of(first)
    assert "Module updated" in text and "Information" in text
    second = text_of(by_marker(tree, "notice-" + INBOX["groups"][1]["ids"][0]))
    assert "Quota threshold reached" in second and "High" in second and "2 times" in second
    assert "Percent" in second and "80" in second and "percent=80" not in second
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", second)
    badge = find_all(tree, lambda n: "sy-sev-high" in str(n["props"].get("className", "")))
    assert badge and "Act today" in json.dumps(badge[0])  # the meaning is on the badge, not only a colour
    note = text_of(by_marker(tree, "inbox-note"))
    assert "nothing leaves this machine" in note.lower() and "model" in note.lower()


def test_h5_wp4_inbox_filter_and_acknowledge_send_the_right_requests() -> None:
    ids = INBOX["groups"][1]["ids"]
    out = render(
        view="Inbox",
        state=["open", loaded(INBOX), ""],
        clicks=[{"target": "filter-acked"}, {"target": "ack-" + ids[0]}],
    )
    pressed = {
        m: by_marker(out["tree"], m)["props"]["aria-pressed"]
        for m in ("filter-open", "filter-acked", "filter-all")
    }
    assert pressed == {"filter-open": "true", "filter-acked": "false", "filter-all": "false"}
    assert [0, "acked"] in out["clicks"][0]["sets"]
    sent = [url for url, _options in out["clicks"][1]["fetches"]]
    assert sent == [f"{BASE}/inbox/{i}/ack" for i in ids]  # every notice in the group
    assert all(options == {"method": "POST"} for _url, options in out["clicks"][1]["fetches"])


def test_h5_wp4_inbox_empty_states_and_failures_are_said_in_words() -> None:
    empty = inbox_view({"items": []})
    assert "Nothing needs your attention" in text_of(
        render(view="Inbox", state=["open", loaded(empty), ""])["tree"]
    )
    assert "No acknowledged notices" in text_of(
        render(view="Inbox", state=["acked", loaded(empty), ""])["tree"]
    )
    failed = render(view="Inbox", state=["open", loaded(INBOX), "Signalbox API is off"])["tree"]
    alert = by_marker(failed, "inbox-error")
    assert alert["props"]["role"] == "alert" and "Signalbox API is off" in text_of(alert)
    ids = INBOX["groups"][0]["ids"]
    out = render(
        view="Inbox",
        state=["open", loaded(INBOX), ""],
        clicks=[{"target": "ack-" + ids[0]}],
        failures={f"{BASE}/inbox/{ids[0]}/ack": "refused"},
    )
    assert [2, "refused"] in out["clicks"][0]["sets"] and out.get("refreshed") is None


def test_h5_wp4_no_view_discards_a_failure_and_the_report_box_is_not_clipped() -> None:
    js = INDEX.read_text(encoding="utf-8")
    assert "props.refresh, props.refresh" not in js
    assert "JSON.stringify(st.data, null, 2)" not in js
    css = (INDEX.parent / "style.css").read_text(encoding="utf-8")
    assert "max-height" not in css
