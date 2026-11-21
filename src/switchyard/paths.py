"""Data-directory resolution and layout (spec section 2).

Order: ``SWITCHYARD_DATA_DIR`` environment variable, configured ``data_dir``, the Hermes plugin data
directory, then the platform default. Every chosen path must be absolute.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from switchyard.errors import ConfigError

APP_NAME = "switchyard"
ENV_VAR = "SWITCHYARD_DATA_DIR"
SUBDIRS: tuple[str, ...] = ("audit", "logs", "staging", "modules", "backup")
_DIR_MODE = 0o700


def _absolute(path: Path, source: str) -> Path:
    if not path.is_absolute():
        raise ConfigError(f"{source} must be an absolute path, got {str(path)!r}")
    return path


def default_data_dir(
    *, platform: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    """Platform user-data location for Switchyard."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if platform == "win32":
        local = env.get("LOCALAPPDATA", "")
        base = Path(local) if local and Path(local).is_absolute() else home / "AppData" / "Local"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        xdg = env.get("XDG_DATA_HOME", "")
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".local" / "share"
    return base / APP_NAME


def resolve_data_dir(
    *,
    env: Mapping[str, str] | None = None,
    configured: Path | None = None,
    hermes_dir: Path | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """Pick the data directory by precedence. Raises ``ConfigError`` on a relative path.

    An explicit directory (``--data-dir``, or ``Core(data_dir=...)``) wins over ``SWITCHYARD_DATA_DIR``, which
    wins over the Hermes profile directory and the platform default (H1 A-1: a caller that names a directory
    must never write into the store the variable points at)."""
    env = os.environ if env is None else env
    if configured is not None:
        return _absolute(configured, "data_dir")
    override = env.get(ENV_VAR, "")
    if override:
        return _absolute(Path(override), ENV_VAR)
    if hermes_dir is not None:
        return _absolute(hermes_dir, "Hermes plugin data directory")
    return default_data_dir(platform=platform, env=env, home=home)


def data_dir_source(
    *, env: Mapping[str, str] | None = None, configured: Path | None = None, hermes_dir: Path | None = None
) -> str:
    """Why ``resolve_data_dir`` picks what it picks (same precedence), for ``config show`` (H1 D-10)."""
    env = os.environ if env is None else env
    if configured is not None:
        return "--data-dir option (or the data_dir argument)"
    if env.get(ENV_VAR, ""):
        return f"{ENV_VAR} environment variable"
    if hermes_dir is not None:
        return "Hermes plugin data directory of the profile"
    return "platform default (the CLI and a Hermes session differ unless SWITCHYARD_DATA_DIR is set)"


def _make_private_dir(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise ConfigError(f"{path} exists and is not a directory")
    path.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, _DIR_MODE)


def ensure_data_dir(path: Path) -> Path:
    """Create the data directory and its subdirectories, user-only on POSIX. Idempotent."""
    _make_private_dir(path)
    for name in SUBDIRS:
        _make_private_dir(path / name)
    return path
