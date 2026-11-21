"""Exception hierarchy. Messages must never contain secret values."""

from __future__ import annotations

from collections.abc import Sequence


class SwitchyardError(Exception):
    """Base class for every error the core raises on purpose."""


# The three kinds a caller may need to tell apart without matching message text (H1 A-31).
class UsageError(SwitchyardError):
    """The operation or its parameters are invalid: unknown names, bad values, wrong types."""


class PolicyRefused(SwitchyardError):
    """Refused by policy: a capability not held, or something the module's manifest did not declare."""


class NotAvailable(SwitchyardError):
    """A service, backend or module the call needs is not there or not running (fail closed)."""


class ConfigError(SwitchyardError):
    """Invalid configuration or data-directory setting."""


class ManifestError(SwitchyardError):
    """A ``module.toml`` failed to load or validate. ``errors`` holds every problem found."""

    def __init__(self, path: object, errors: Sequence[str]) -> None:
        self.path = str(path)
        self.errors: tuple[str, ...] = tuple(errors)
        super().__init__(f"{self.path}: " + "; ".join(self.errors))


class CapabilityDenied(PolicyRefused):
    """A module asked for a capability it does not hold."""


class StateError(SwitchyardError):
    """State store misuse or migration failure."""


class AuditError(SwitchyardError):
    """The audit log could not be written or failed verification."""


class UpdateError(SwitchyardError):
    """A module update failed verification or could not be applied."""


class ChannelNotFound(UpdateError, NotAvailable):
    """The update channel (branch or tag) does not exist at the module's source."""
