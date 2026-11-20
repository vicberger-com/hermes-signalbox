"""The module contract suite, applied to the shipped template and to modules that break the contract."""

from __future__ import annotations

from pathlib import Path

import pytest
from sy_testing import GOOD, write_module

from switchyard.contract import run_contract

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "module"


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


def _names(report: object) -> dict[str, bool]:
    return {c.name: c.ok for c in report.checks}  # type: ignore[attr-defined]


def test_template_module_passes_the_full_contract() -> None:
    report = run_contract(TEMPLATE, bundled=True)
    assert report.ok, report.summary()
    assert list(_names(report)) == [
        "manifest",
        "trust",
        "discover",
        "deny_ungranted",
        "activate",
        "health",
        "panels",
        "deactivate",
        "remove",
        "audit",
    ]
    assert "net.outbound" in report.checks[3].detail
    assert "PASS" in report.summary()
    assert not list(TEMPLATE.glob("data")), "the contract must not write into the module directory"


def test_template_passes_under_the_subprocess_host(tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "example"
    shutil.copytree(TEMPLATE, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    toml = copy / "module.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('isolation = "in-process"', 'isolation = "subprocess"'),
        encoding="utf-8",
    )
    report = run_contract(copy)
    assert report.ok, report.summary()


def test_invalid_manifest_fails_first_check(tmp_path: Path) -> None:
    (tmp_path / "module.toml").write_text("schema = 2\n", encoding="utf-8")
    report = run_contract(tmp_path)
    assert not report.ok and _names(report) == {"manifest": False}
    assert "<unknown>" in report.summary()


def test_unhealthy_module_fails_and_later_checks_are_skipped(tmp_path: Path) -> None:
    code = GOOD.replace('return (self.ctx is not None, "ok")', 'return (False, "broken")')
    d = write_module(tmp_path, "sick", code, request=("ui.panel",))
    report = run_contract(d, bundled=True)
    names = _names(report)
    assert names["activate"] and not names["health"] and "panels" not in names and names["audit"]
    assert "broken" in report.summary()


def test_module_that_fails_to_activate(tmp_path: Path) -> None:
    code = GOOD.replace('ctx.log("{id}", "activated")', 'raise RuntimeError("boom")')
    report = run_contract(write_module(tmp_path, "crash", code), bundled=True)
    assert _names(report)["activate"] is False and "failed" in report.summary()


def test_declared_panel_that_is_never_registered_fails(tmp_path: Path) -> None:
    # GOOD declares "<id>.status" (write_module) but never registers it.
    report = run_contract(write_module(tmp_path, "nopanel", request=("ui.panel",)), bundled=True)
    names = _names(report)
    assert names["health"] and names["panels"] is False, report.summary()
    assert "declared ['nopanel.status']" in report.summary()


def test_denial_probe_switches_when_module_requests_net(tmp_path: Path) -> None:
    d = write_module(tmp_path, "netty", request=("ui.panel",))
    toml = d / "module.toml"
    text = toml.read_text(encoding="utf-8")
    text = text.replace('request = ["ui.panel"]', 'request = ["ui.panel", "net.outbound"]')
    text = text.replace("[contributes]", 'net_hosts = ["example.invalid"]\n[contributes]')
    toml.write_text(text, encoding="utf-8")
    report = run_contract(d, bundled=True)
    assert report.checks[3].detail == "process.spawn", report.summary()
    assert _names(report)["audit"]


@pytest.mark.parametrize("settings", [{"bad key": 1}, {"k\n[x]": 1}, {"k": None}, {"k": [None]}, {"k": 1.5}])
def test_contract_settings_are_validated(settings: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        run_contract(TEMPLATE, settings=settings, bundled=True)
