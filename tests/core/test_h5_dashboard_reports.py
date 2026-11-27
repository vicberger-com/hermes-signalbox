"""H5 WP4 (#207, #208): what the Reports and Inbox views show, prepared in the typed dashboard support
module so the page only lays it out: sentences instead of audit records, labelled fields instead of
``key=value`` strings, repeats grouped.
"""

from __future__ import annotations

from typing import Any

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


def _report(kind: str, **payload: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind, **payload}
    out.update(purpose=reports.PURPOSES[kind], summary=reports.summarize(out, modules=payload.get("modules")))
    return out


def test_h5_wp4_changes_become_a_timeline_of_sentences_newest_first() -> None:
    changes = [_rec(1, "policy.granted", capability="ui.panel"), _rec(2, "module.activated", actor="api")]
    view = report_view(_report("changes", changes=changes))
    assert view["rows"] == [
        {"when": changes[1]["ts"], "who": "Dashboard", "what": "Dashboard started router", "count": 1},
        {
            "when": changes[0]["ts"],
            "who": "CLI",
            "what": "CLI granted router the permission to show a dashboard panel",
            "count": 1,
        },
    ]
    assert "hhhhhhhh" not in str(view)  # chain hashes stay in the raw data


def test_h5_wp4_repeated_refusals_are_grouped_and_labelled() -> None:
    denials = [
        _rec(1, "policy.denied", actor="core", capability="hermes.hooks", operation="module activate"),
        _rec(2, "policy.denied", actor="core", capability="hermes.hooks", operation="module activate"),
        _rec(3, "policy.denied", module="meter", actor="core", capability="ui.panel"),
    ]
    audit = {"ok": True, "records": 3, "first_bad_seq": None, "reason": ""}
    view = report_view(_report("security", audit=audit, recent_denials=denials))
    assert view["audit_ok"] is True
    assert view["rows"] == [
        {
            "when": denials[2]["ts"],
            "who": "Signalbox",
            "module": "meter",
            "what": "Permission refused",
            "permission": "Show a dashboard panel (ui.panel)",
            "count": 1,
        },
        {
            "when": denials[1]["ts"],
            "who": "Signalbox",
            "module": "router",
            "what": "Permission refused",
            "permission": "Watch and steer Hermes requests (hermes.hooks)",
            "count": 2,
        },
    ]


def test_h5_wp4_health_rows_put_failures_first_and_name_what_is_needed() -> None:
    def row(mid: str, status: str, missing: tuple[str, ...] = (), error: str | None = None) -> dict[str, Any]:
        return {
            "id": mid,
            "version": "0.1.0",
            "status": status,
            "mode": "auto",
            "error": error,
            "missing_grants": list(missing),
        }

    modules = [
        row("aaa", "active"),
        row("bbb", "verified", ("schedule",)),
        row("ccc", "failed", error="boom"),
    ]
    view = report_view(_report("health", modules=modules, failed=["ccc"]))
    assert [r["id"] for r in view["rows"]] == ["ccc", "aaa", "bbb"]
    assert view["rows"][0] == {"id": "ccc", "state": "Error", "detail": "boom", "needs": []}
    assert view["rows"][2] == {
        "id": "bbb",
        "state": "Ready, needs permissions",
        "detail": "",
        "needs": ["Run on a timer (schedule)"],
    }


def test_h5_wp4_usage_sections_list_only_what_reports_and_hide_empty_values() -> None:
    payload = {
        "meter": {"unavailable": "not active"},
        "router": {
            "provider": "openrouter",
            "max_attempts": 3,
            "pins": {},
            "hard_stop": False,
            "last": None,
            "budget": {"paid_requests_per_day": 0},
        },
    }
    view = report_view(_report("usage", **payload))
    assert view["sections"] == [
        {
            "name": "router",
            "lines": [
                "provider: openrouter",
                "max attempts: 3",
                "hard stop: no",
                "budget, paid requests per day: 0",
            ],
        }
    ]


def test_h5_wp4_an_unknown_report_shape_gives_an_empty_view_not_an_error() -> None:
    assert report_view({"kind": "health"}) == {"rows": []}
    assert report_view({"kind": "other"}) == {}
    assert report_view("nonsense") == {}


def test_h5_wp4_inbox_groups_repeats_and_labels_the_detail_fields() -> None:
    items = [
        _item(3),
        _item(2),
        _item(
            1,
            severity="critical",
            type="core.notify",
            module="supervisor",
            title="Audit check failed",
            detail="Record 7 does not match.",
        ),
    ]
    view = inbox_view({"items": items})
    assert view["items"] == items  # the raw list is still there
    assert view["open"] == 3
    first, second = view["groups"]
    assert first == {
        "ids": [items[0]["id"], items[1]["id"]],
        "count": 2,
        "at": items[0]["at"],
        "module": "meter",
        "severity": "high",
        "severity_label": "High",
        "severity_meaning": "Act today: a module failed or a limit was reached.",
        "title": "Quota threshold reached",
        "state": "open",
        "text": "",
        "fields": [{"label": "Percent", "value": "80"}, {"label": "Quota", "value": "day"}],
    }
    assert second["text"] == "Record 7 does not match." and second["fields"] == []
    assert second["severity_label"] == "Critical" and second["count"] == 1


def test_h5_wp4_inbox_keeps_free_text_that_only_looks_like_fields_as_text() -> None:
    [group] = inbox_view({"items": [_item(1, detail="see a=b, then retry")]})["groups"]
    assert group["fields"] == [] and group["text"] == "see a=b, then retry"
    assert inbox_view({"items": []}) == {"items": [], "groups": [], "open": 0}
    assert inbox_view({"unexpected": 1}) == {"items": [], "groups": [], "open": 0}
    acked = inbox_view({"items": [_item(1, state="acked"), _item(2)]})
    assert (
        acked["open"] == 1 and len(acked["groups"]) == 2
    )  # an acknowledged copy is not merged into an open one
