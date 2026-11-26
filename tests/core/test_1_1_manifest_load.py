"""1.1 backlog batch 9: manifest and config files are size-checked before being read whole (H1 A-16 #89)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_signalbox import config, manifest
from hermes_signalbox.errors import ConfigError, ManifestError


def _no_whole_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self: Path) -> bytes:
        raise AssertionError(f"{self.name} was read whole before its size was checked")

    monkeypatch.setattr(Path, "read_bytes", refuse)


def test_h1_a16_oversize_manifest_is_refused_without_reading_it_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "module.toml"
    path.write_bytes(b"#" * (manifest.MAX_MANIFEST_BYTES + 10))
    _no_whole_reads(monkeypatch)
    with pytest.raises(ManifestError, match="too large"):
        manifest._read(path)


def test_h1_a16_oversize_config_is_refused_without_reading_it_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"#" * (config.MAX_CONFIG_BYTES + 10))
    _no_whole_reads(monkeypatch)
    with pytest.raises(ConfigError, match="too large"):
        config.load_config(path)


def test_h1_a16_files_at_the_limit_still_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b"#" * config.MAX_CONFIG_BYTES)
    _no_whole_reads(monkeypatch)
    assert config.load_config(path) == config.CoreConfig()
    assert config.load_config(tmp_path / "missing.toml") == config.CoreConfig()
