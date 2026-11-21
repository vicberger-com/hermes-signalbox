"""Core configuration: ``<data_dir>/config.toml`` read with ``tomllib``.

Keys::

    data_dir = "/abs/path"       # optional
    [api]  enabled = false       # loopback control API off by default
           port = 0              # 0 = ephemeral
    [log]  level = "INFO"        # DEBUG | INFO | WARNING | ERROR
    [host] profile = "auto"      # auto | tiny | laptop | workstation | server
    [tools] git = "/abs/git"     # optional: the git to use (default: first runnable git on PATH)

Unknown keys are errors so a typo cannot silently fall back to a default.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from switchyard.errors import ConfigError

MAX_CONFIG_BYTES = 64 * 1024
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})
HOST_PROFILES = frozenset({"auto", "tiny", "laptop", "workstation", "server"})


@dataclass(frozen=True)
class ApiConfig:
    enabled: bool = False
    port: int = 0


@dataclass(frozen=True)
class CoreConfig:
    data_dir: Path | None = None
    api: ApiConfig = field(default_factory=ApiConfig)
    log_level: str = "INFO"
    host_profile: str = "auto"
    modules: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # [modules.<id>] tables
    git: str | None = None  # [tools] git: absolute path (H1 D-2)


def _table(doc: Mapping[str, Any], key: str, allowed: frozenset[str]) -> Mapping[str, Any]:
    value = doc.get(key, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key}: expected a table")
    unknown = set(value) - allowed
    if unknown:
        raise ConfigError(f"{key}: unknown key(s) {sorted(unknown)}")
    return value


def _choice(value: Any, name: str, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ConfigError(f"{name}: must be one of {sorted(allowed)}")
    return value


def parse_config(doc: Mapping[str, Any]) -> CoreConfig:
    """Validate a parsed TOML document and build ``CoreConfig``."""
    unknown = set(doc) - {"data_dir", "api", "log", "host", "modules", "tools"}
    if unknown:
        raise ConfigError(f"unknown key(s) {sorted(unknown)}")

    data_dir: Path | None = None
    if "data_dir" in doc:
        raw = doc["data_dir"]
        if not isinstance(raw, str):
            raise ConfigError("data_dir: expected a string")
        data_dir = Path(raw)
        if not data_dir.is_absolute():
            raise ConfigError(f"data_dir must be an absolute path, got {raw!r}")

    api = _table(doc, "api", frozenset({"enabled", "port"}))
    enabled = api.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("api.enabled: expected true or false")
    port = api.get("port", 0)
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ConfigError("api.port: expected an integer from 0 to 65535")

    level = _choice(_table(doc, "log", frozenset({"level"})).get("level", "INFO"), "log.level", LOG_LEVELS)
    profile = _choice(
        _table(doc, "host", frozenset({"profile"})).get("profile", "auto"), "host.profile", HOST_PROFILES
    )
    git = _table(doc, "tools", frozenset({"git"})).get("git")
    if git is not None and (not isinstance(git, str) or not Path(git).is_absolute()):
        raise ConfigError("tools.git: expected an absolute path")
    modules = doc.get("modules", {})
    if not isinstance(modules, Mapping) or not all(isinstance(v, Mapping) for v in modules.values()):
        raise ConfigError("modules: expected one table per module id ([modules.<id>])")
    return CoreConfig(
        data_dir=data_dir, api=ApiConfig(enabled, port), log_level=level, host_profile=profile,
        modules={str(k): dict(v) for k, v in modules.items()}, git=git,
    )  # fmt: skip


def load_config(path: Path) -> CoreConfig:
    """Load ``path``; a missing file yields defaults."""
    from switchyard.paths import read_limited

    try:
        raw = read_limited(path, MAX_CONFIG_BYTES)
    except FileNotFoundError:
        return CoreConfig()
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read config: {exc}") from exc
    if raw is None:
        raise ConfigError(f"{path}: config file too large (limit {MAX_CONFIG_BYTES} bytes)")
    try:
        doc = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read config: {exc}") from exc
    return parse_config(doc)
