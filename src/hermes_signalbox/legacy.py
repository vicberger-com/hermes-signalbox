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
  kept for rollback, with a marker file added so that it is copied once.
  A directory that contains a link (symbolic
  link or Windows junction) is refused: the copy would follow it.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import stat
import sys
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_signalbox.errors import ConfigError

LEGACY_NAME = "switchyard"
LEGACY_PREFIX = "SWITCHYARD_"
NEW_PREFIX = "SIGNALBOX_"
# Written into the old directory after its copy succeeded. A directory that carries it is not copied
# again: without it, losing the new state (a reset, a reinstall) would bring the 1.0.x state back,
# grants revoked since included (independent review R-7). Delete the file to copy again on purpose.
MARKER = "migrated-to-signalbox.txt"
# Runtime files of the process that owned the old directory, and the marker; never copied.
_RUNTIME_FILES = frozenset({"host.lock", "api.port", "api.token", MARKER})
_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT; ``stat`` names it on Windows only
_log = logging.getLogger("signalbox.legacy")


def legacy_env(env: Mapping[str, str], name: str) -> tuple[str, str]:
    """``(value, variable)`` for ``SIGNALBOX_<name>``, falling back to the deprecated ``SWITCHYARD_<name>``.

    Returns ``("", new_variable)`` when neither is set. Reading the old name warns each time it is read."""
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


def _is_link(path: Path) -> bool:
    """A symbolic link, or on Windows any reparse point (a directory junction needs no privilege)."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _first_link(root: Path) -> Path | None:
    """The first link inside ``root``, or ``None``. ``os.walk`` does not descend into links."""
    for directory, folders, files in os.walk(root):
        for name in sorted([*folders, *files]):
            if _is_link(Path(directory) / name):
                return Path(directory) / name
    return None


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
    named = sorted(parent.glob(f"agent-plugin-{LEGACY_NAME}-*")) if hermes else [parent / LEGACY_NAME]
    found = []
    for path in named:
        if _is_link(path):  # checked first: looking inside a link already reads from where it points
            _log.warning("%s is a link and is not used as a %s data directory", path, LEGACY_NAME)
        elif path.is_dir() and _has_state(path) and not (path / MARKER).exists():
            found.append(path)
    return found


def _state_problem(path: Path) -> str:
    """Why the copied state file cannot be trusted, or ``""``. A copy taken while something was writing,
    or a file that is not a database, is refused before it becomes the new state."""
    try:
        connection = sqlite3.connect(path)
        try:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return str(exc)
    return "" if rows == [("ok",)] else "; ".join(str(r[0]) for r in rows[:3])


def _make_private(root: Path) -> None:
    """Copied files keep the permission bits they had. Narrow them to the owner (POSIX; on Windows the
    profile directory's access list applies)."""
    if sys.platform == "win32":
        return
    os.chmod(root, 0o700)
    for directory, folders, files in os.walk(root):
        for name in folders:
            os.chmod(Path(directory) / name, 0o700)
        for name in files:
            os.chmod(Path(directory) / name, 0o600)


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
    if _is_link(source):
        raise ConfigError(
            f"{source} is a link; nothing was copied. Copy the directory it points to to {new_dir} by hand"
        )
    try:
        return _copy(source, new_dir, AuditLog, HostLock)
    except OSError as exc:  # a read-only or vanished directory, a special file: one clear line, no traceback
        raise ConfigError(f"could not copy {source} ({exc}); nothing was copied") from exc


def _copy(source: Path, new_dir: Path, AuditLog: Any, HostLock: Any) -> Migration | None:
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
        # H5 review R-3: ``copytree`` follows links, so a link in the old directory would pull files from
        # outside it into the new one (or never end, for a link to a parent). Refuse instead of guessing.
        link = _first_link(source)
        if link is not None:
            raise ConfigError(
                f"{source} contains a link ({link.relative_to(source)}); nothing was copied. Replace the "
                f"link with the files it points to, or copy the directory to {new_dir} by hand"
            )
        shutil.copytree(source, staging, ignore=lambda _d, names: [n for n in names if n in _RUNTIME_FILES])
        result = AuditLog.verify_directory(staging / "audit")
        if not result.ok:
            raise ConfigError(
                f"the audit log in {source} does not verify "
                f"({result.reason} at record {result.first_bad_seq}); "
                "nothing was copied"
            )
        problem = _state_problem(staging / "state.db")
        if problem:
            raise ConfigError(f"state.db in {source} is damaged ({problem}); nothing was copied")
        _make_private(staging)
        if new_dir.exists():
            if any(new_dir.iterdir()):
                raise ConfigError(f"{new_dir} is not empty; nothing was copied")
            new_dir.rmdir()
        os.replace(staging, new_dir)
        try:
            (source / MARKER).write_text(
                f"This directory was copied to {new_dir} when Signalbox 1.1 first started.\n"
                "Signalbox does not read it again. It is kept so that you can go back to 1.0.x.\n"
                "Delete this file only if you want Signalbox to copy this directory again.\n",
                encoding="utf-8",
            )
        except OSError as exc:
            _log.warning("could not mark %s as copied: %s", source, exc)
        return Migration(source=source, target=new_dir, records=result.records)
    finally:
        lock.release()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
