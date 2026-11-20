"""Data-directory resolution (spec section 2)."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from switchyard.errors import ConfigError
from switchyard.paths import SUBDIRS, default_data_dir, ensure_data_dir, resolve_data_dir


def test_env_override_wins(tmp_path: Path) -> None:
    env = {"SWITCHYARD_DATA_DIR": str(tmp_path / "env")}
    got = resolve_data_dir(env=env, configured=tmp_path / "cfg", hermes_dir=tmp_path / "hermes")
    assert got == tmp_path / "env"


def test_configured_beats_hermes_and_default(tmp_path: Path) -> None:
    got = resolve_data_dir(env={}, configured=tmp_path / "cfg", hermes_dir=tmp_path / "hermes")
    assert got == tmp_path / "cfg"


def test_hermes_dir_beats_platform_default(tmp_path: Path) -> None:
    assert resolve_data_dir(env={}, hermes_dir=tmp_path / "hermes") == tmp_path / "hermes"


def test_relative_paths_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="absolute"):
        resolve_data_dir(env={"SWITCHYARD_DATA_DIR": "relative/dir"})
    with pytest.raises(ConfigError, match="absolute"):
        resolve_data_dir(env={}, configured=Path("rel"))


def test_empty_env_value_is_ignored(tmp_path: Path) -> None:
    assert resolve_data_dir(env={"SWITCHYARD_DATA_DIR": ""}, configured=tmp_path) == tmp_path


@pytest.mark.parametrize(
    ("platform", "env", "expected_parts"),
    [
        ("win32", {"LOCALAPPDATA": "LAD"}, ("LAD", "switchyard")),
        ("win32", {}, ("HOME", "AppData", "Local", "switchyard")),
        ("darwin", {}, ("HOME", "Library", "Application Support", "switchyard")),
        ("linux", {"XDG_DATA_HOME": "XDG"}, ("XDG", "switchyard")),
        ("linux", {}, ("HOME", ".local", "share", "switchyard")),
    ],
)
def test_platform_defaults(
    tmp_path: Path, platform: str, env: dict[str, str], expected_parts: tuple[str, ...]
) -> None:
    home = tmp_path / "HOME"
    env = {k: str(tmp_path / v) for k, v in env.items()}
    got = default_data_dir(platform=platform, env=env, home=home)
    assert got == tmp_path.joinpath(*expected_parts)


def test_relative_xdg_is_ignored(tmp_path: Path) -> None:
    got = default_data_dir(platform="linux", env={"XDG_DATA_HOME": "rel"}, home=tmp_path)
    assert got == tmp_path / ".local" / "share" / "switchyard"


def test_ensure_creates_layout(tmp_path: Path) -> None:
    root = ensure_data_dir(tmp_path / "data")
    for name in SUBDIRS:
        assert (root / name).is_dir()
    assert ensure_data_dir(root) == root  # idempotent


def test_ensure_refuses_a_file(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="not a directory"):
        ensure_data_dir(target)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_ensure_is_user_only_on_posix(tmp_path: Path) -> None:
    root = ensure_data_dir(tmp_path / "data")
    for path in (root, *(root / n for n in SUBDIRS)):
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o700
