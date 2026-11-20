"""Exception hierarchy. Messages must never contain secret values."""

from __future__ import annotations

from collections.abc import Sequence


class SwitchyardError(Exception):
    """Base class for every error the core raises on purpose."""


class ConfigError(SwitchyardError):
    """Invalid configuration or data-directory setting."""


class ManifestError(SwitchyardError):
    """A ``module.toml`` failed to load or validate. ``errors`` holds every problem found."""

    def __init__(self, path: object, errors: Sequence[str]) -> None:
        self.path = str(path)
        self.errors: tuple[str, ...] = tuple(errors)
        super().__init__(f"{self.path}: " + "; ".join(self.errors))


class CapabilityDenied(SwitchyardError):
    """A module asked for a capability it does not hold."""


class StateError(SwitchyardError):
    """State store misuse or migration failure."""


class AuditError(SwitchyardError):
    """The audit log could not be written or failed verification."""


class UpdateError(SwitchyardError):
    """A module update failed verification or could not be applied."""
