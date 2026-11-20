"""Suite-wide fixtures."""

from collections.abc import Iterator

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "bundled_modules: run with the bundled modules (M1+) discoverable")


@pytest.fixture(autouse=True)
def _no_bundled_modules(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Tests run without the bundled modules unless marked ``bundled_modules``, so module lists contain only
    what a test writes."""
    if request.node.get_closest_marker("bundled_modules") is None:
        monkeypatch.setattr("switchyard.core.BUILTIN_MODULES", tmp_path_factory.mktemp("no-bundled-modules"))
    yield
