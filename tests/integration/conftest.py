"""Real-Hermes tests use the adapter's real process-role check (ADR-0014), not the suite's stand-in."""

import pytest


@pytest.fixture(autouse=True)
def _adapter_is_the_gateway() -> None:
    """Replaces the suite-wide fixture of the same name: this process is not a gateway, and Hermes says so."""
