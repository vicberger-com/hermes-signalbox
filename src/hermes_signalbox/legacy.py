"""Upgrade path from the plugin's former name, Switchyard (H5, ADR-0015).

Version 1.1.0 renamed the plugin from ``switchyard`` to ``signalbox``.
Three things a 1.0.x user may still have:

* **Environment variables** ``SWITCHYARD_DATA_DIR`` and
  ``SWITCHYARD_SECRET_<NAME>``. They are still read in 1.1.x, with a
  deprecation warning; the new ``SIGNALBOX_*`` name wins when both are set.
* **Stored secrets** under the old keychain service / Windows credential
  prefix ``switchyard``. Backends read them when the new name has no entry;
  writes always go to the new name.
* **A data directory** under the old name (``plugin-data/agent-plugin-
  switchyard-<hash>`` in Hermes, or the platform default ``.../switchyard``).
  On first start, when the new directory holds no state yet and exactly one
  old directory does, the old one is **copied** (never moved), with its host
  lock held so no 1.0.x process hosts it meanwhile. The copy goes to a
  temporary sibling and is renamed into place only after its audit chain
  verifies, so a failure leaves no partial directory. The old directory is
  left as it was, for rollback.
"""

from __future__ import annotations

import logging
import os
import shutil
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from hermes_signalbox.errors import ConfigError

LEGACY_NAME = "switchyard"
LEGACY_PREFIX = "SWITCHYARD_"
NEW_PREFIX = "SIGNALBOX_"
# Runtime files of the process that owned the old directory; never copied.
_RUNTIME_FILES = frozenset({"host.lock", "api.port", "api.token"})
_log = logging.getLogger("signalbox.legacy")


def legacy_env(env: Mapping[str, str], name: str) -> tuple[str, str]:
    """``(value, variable)`` for ``SIGNALBOX_<name>``, falling back to the deprecated ``SWITCHYARD_<name>``.

    Returns ``("", new_variable)`` when neither is set. Reading the old name warns once per call site."""
    new, old = NEW_PREFIX + name, LEGACY_PREFIX + name
    value = env.get(new, "")
    if value:
        return value, new
    value = env.get(old, "")
    if value:
        warnings.warn(
            f"{old} is deprecated since 1.1.0; rename it to {new}", DeprecationWarning, stacklevel=3
        )
        _log.warning("%s is deprecated since 1.1.0; rename it to %s", old, new)
        return value, old
    return "", new


def _has_state(path: Path) -> bool:
    return (path / "state.db").is_file()


def legacy_candidates(new_dir: Path, *, hermes: bool) -> list[Path]:
    """Old-name directories that could hold this install's 1.0.x state.

    In Hermes the data directory is ``<plugin-data>/agent-plugin-<name>-<hash>``, so the candidates are the
    siblings named ``agent-plugin-switchyard-*``. Outside Hermes it is the platform default, so the candidate
    is the sibling named ``switchyard``."""
    parent = new_dir.parent
    if not parent.is_dir():
        return []
    if hermes:
        found = sorted(p for p in parent.glob(f"agent-plugin-{LEGACY_NAME}-*") if p.is_dir())
    else:
        found = [parent / LEGACY_NAME] if (parent / LEGACY_NAME).is_dir() else []
    return [p for p in found if _has_state(p)]


@dataclass(frozen=True)
class Migration:
    source: Path
    target: Path
    records: int


def migrate_data_dir(new_dir: Path, candidates: list[Path]) -> Migration | None:
    """Copy a 1.0.x data directory to ``new_dir`` when ``new_dir`` has no state yet.

    Returns ``None`` when there is nothing to do (state already present, or no candidate). Raises
    ``ConfigError`` when more than one candidate exists, the old directory is in use, or its copy does not
    verify; nothing is written in those cases."""
    # Imported here: the audit and lock modules import paths, which imports this module.
    from hermes_signalbox.audit import AuditLog
    from hermes_signalbox.hostlock import HostLock

    if _has_state(new_dir) or not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(str(p) for p in candidates)
        raise ConfigError(
            f"found several Switchyard data directories ({names}); copy the right one to {new_dir} by hand "
            f"or set {NEW_PREFIX}DATA_DIR"
        )
    source = candidates[0]
    lock = HostLock(source / "host.lock")
    if not lock.acquire():
        if _has_state(new_dir):  # another Signalbox process finished the copy while we looked
            return None
        raise ConfigError(
            f"{source} is in use by a Switchyard 1.0.x process; stop it (or uninstall Switchyard and restart "
            "Hermes), then start Signalbox again to copy its data"
        )
    staging = new_dir.with_name(new_dir.name + ".migrating")
    try:
        if _has_state(new_dir):  # copied by another Signalbox process before we took the lock
            return None
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging, ignore=lambda _d, names: [n for n in names if n in _RUNTIME_FILES])
        result = AuditLog.verify_directory(staging / "audit")
        if not result.ok:
            raise ConfigError(
                f"the audit log in {source} does not verify "
                f"({result.reason} at record {result.first_bad_seq}); "
                "nothing was copied"
            )
        if new_dir.exists():
            if any(new_dir.iterdir()):
                raise ConfigError(f"{new_dir} is not empty; nothing was copied")
            new_dir.rmdir()
        os.replace(staging, new_dir)
        return Migration(source=source, target=new_dir, records=result.records)
    finally:
        lock.release()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
