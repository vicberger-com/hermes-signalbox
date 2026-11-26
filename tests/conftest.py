"""Suite-wide fixtures and the per-platform skip check (``tools/skip_allowlist.py``)."""

import os
from collections.abc import Iterator

import pytest

_SKIPPED: set[str] = set()
_PASSED: set[str] = set()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "bundled_modules: run with the bundled modules (M1+) discoverable")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped and report.when in ("setup", "call"):
        _SKIPPED.add(report.nodeid)
    elif report.passed and report.when == "call":
        _PASSED.add(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """H1 D-12: in CI (``SIGNALBOX_CHECK_SKIPS=1``) the skipped set must match this platform's allow-list."""
    if os.environ.get("SIGNALBOX_CHECK_SKIPS") != "1":
        return
    from skip_allowlist import allowed, compare

    problems = compare(_SKIPPED, _PASSED, allowed())
    if problems:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        for line in problems:
            if reporter is not None:
                reporter.write_line(f"skip allow-list: {line}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def _no_bundled_modules(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Tests run without the bundled modules unless marked ``bundled_modules``, so module lists contain only
    what a test writes."""
    if request.node.get_closest_marker("bundled_modules") is None:
        monkeypatch.setattr(
            "hermes_signalbox.core.BUILTIN_MODULES", tmp_path_factory.mktemp("no-bundled-modules")
        )
    yield


@pytest.fixture(autouse=True)
def _adapter_is_the_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter tests stand for the Hermes gateway process, which hosts at plugin load (H4 R1-F8, ADR-0014).
    Tests of the other process roles replace this again (``tests/core/test_h4_hosting.py``)."""
    monkeypatch.setattr("hermes_signalbox.hermes._gateway_runtime", lambda: True)
