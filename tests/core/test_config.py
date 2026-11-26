"""Core configuration (spec sections 2 and 3, Q&A question 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_signalbox.config import MAX_CONFIG_BYTES, CoreConfig, load_config, parse_config
from hermes_signalbox.errors import ConfigError


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "absent.toml")
    assert cfg == CoreConfig()
    assert cfg.api.enabled is False and cfg.api.port == 0
    assert cfg.log_level == "INFO" and cfg.host_profile == "auto" and cfg.data_dir is None


def test_full_file_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    data_dir = (tmp_path / "d").as_posix()
    path.write_text(
        f'data_dir = "{data_dir}"\n[api]\nenabled = true\nport = 8765\n'
        '[log]\nlevel = "DEBUG"\n[host]\nprofile = "laptop"\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.data_dir == Path(data_dir)
    assert cfg.api.enabled is True and cfg.api.port == 8765
    assert cfg.log_level == "DEBUG" and cfg.host_profile == "laptop"


@pytest.mark.parametrize(
    ("doc", "fragment"),
    [
        ({"surprise": 1}, "unknown key"),
        ({"api": {"remote": True}}, "unknown key"),
        ({"api": {"enabled": "yes"}}, "api.enabled"),
        ({"api": {"port": True}}, "api.port"),
        ({"api": {"port": 70000}}, "api.port"),
        ({"api": {"port": -1}}, "api.port"),
        ({"log": {"level": "LOUD"}}, "log.level"),
        ({"host": {"profile": "mainframe"}}, "host.profile"),
        ({"data_dir": 5}, "data_dir"),
        ({"data_dir": "relative"}, "absolute"),
        ({"api": []}, "api"),
    ],
)
def test_bad_values_are_rejected(doc: dict[str, object], fragment: str) -> None:
    with pytest.raises(ConfigError, match=fragment):
        parse_config(doc)


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("api = = 1", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(path)


def test_oversize_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("#" * (MAX_CONFIG_BYTES + 1), encoding="utf-8")
    with pytest.raises(ConfigError, match="too large"):
        load_config(path)


def test_h1_d2_tools_git_must_be_absolute() -> None:
    from hermes_signalbox.config import parse_config
    from hermes_signalbox.errors import ConfigError

    absolute = str(Path(__file__).resolve())
    assert parse_config({"tools": {"git": absolute}}).git == absolute
    assert parse_config({}).git is None
    for bad in ({"tools": {"git": "git"}}, {"tools": {"git": 1}}, {"tools": {"svn": "/x"}}):
        with pytest.raises(ConfigError):
            parse_config(bad)
