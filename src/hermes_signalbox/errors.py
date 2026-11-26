"""Exception hierarchy. Messages must never contain secret values."""

from __future__ import annotations

from collections.abc import Sequence


class SignalboxError(Exception):
    """Base class for every error the core raises on purpose."""


# The three kinds a caller may need to tell apart without matching message text (H1 A-31).
class UsageError(SignalboxError):
    """The operation or its parameters are invalid: unknown names, bad values, wrong types."""


class PolicyRefused(SignalboxError):
    """Refused by policy: a capability not held, or something the module's manifest did not declare."""


class NotAvailable(SignalboxError):
    """A service, backend or module the call needs is not there or not running (fail closed)."""


# H3-23: Split NotAvailable into more specific classes for clearer semantics
class ModuleNotRunning(NotAvailable):
    """The module is not running (not activated or already stopped)."""


class BrokerUnavailableToSubprocess(NotAvailable):
    """A capability broker is not available to subprocess modules in M0."""


class ConfigError(SignalboxError):
    """Invalid configuration or data-directory setting."""


class ManifestError(SignalboxError):
    """A ``module.toml`` failed to load or validate. ``errors`` holds every problem found."""

    def __init__(self, path: object, errors: Sequence[str]) -> None:
        self.path = str(path)
        self.errors: tuple[str, ...] = tuple(errors)
        super().__init__(f"{self.path}: " + "; ".join(self.errors))


class CapabilityDenied(PolicyRefused):
    """A module asked for a capability it does not hold."""


class StateError(SignalboxError):
    """State store misuse or migration failure."""


class AuditError(SignalboxError):
    """The audit log could not be written or failed verification."""


class UpdateError(SignalboxError):
    """A module update failed verification or could not be applied."""


class ChannelNotFound(UpdateError, NotAvailable):
    """The update channel (branch or tag) does not exist at the module's source."""
