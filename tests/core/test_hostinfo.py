"""Host profiler and capacity profiles (spec section 3, Host profiler)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from switchyard.errors import ConfigError
from switchyard.hostinfo import GIB, HostProfile, capacity_metrics, classify, parse_meminfo, profile

MEMINFO = """MemTotal:       16318412 kB
MemFree:         1203400 kB
MemAvailable:    8159206 kB
Buffers:          120000 kB
"""


@pytest.mark.parametrize(
    ("cpus", "ram_gib", "expected"),
    [
        (1, 32, "tiny"),
        (4, 3.5, "tiny"),
        (4, 8, "laptop"),
        (8, 15.9, "laptop"),
        (8, 16, "workstation"),
        (16, 63, "workstation"),
        (32, 64, "server"),
    ],
)
def test_classify(cpus: int, ram_gib: float, expected: str) -> None:
    assert classify(cpus, int(ram_gib * GIB)) == expected


def test_parse_meminfo() -> None:
    total, available = parse_meminfo(MEMINFO)
    assert total == 16318412 * 1024 and available == 8159206 * 1024
    assert parse_meminfo("garbage") == (None, None)


def test_profile_on_this_host(tmp_path: Path) -> None:
    p = profile(data_dir=tmp_path)
    assert isinstance(p, HostProfile)
    assert p.cpu_count >= 1 and p.ram_bytes > 256 * 1024 * 1024 and p.disk_free_bytes > 0
    assert p.profile_name in {"tiny", "laptop", "workstation", "server"}
    assert p.platform == sys.platform and p.net_class == "unknown"
    assert p.to_dict()["profile_name"] == p.profile_name


def test_override_wins(tmp_path: Path) -> None:
    assert profile(data_dir=tmp_path, override="server").profile_name == "server"
    with pytest.raises(ConfigError, match="profile"):
        profile(data_dir=tmp_path, override="mainframe")


def test_injected_readers(tmp_path: Path) -> None:
    p = profile(
        data_dir=tmp_path, cpu_count=lambda: None, memory=lambda: (2 * GIB, GIB), gpu=lambda: "nvidia"
    )
    assert p.cpu_count == 1 and p.ram_bytes == 2 * GIB and p.gpu == "nvidia" and p.profile_name == "tiny"


def test_unknown_memory_is_treated_as_tiny(tmp_path: Path) -> None:
    p = profile(data_dir=tmp_path, cpu_count=lambda: 8, memory=lambda: (None, None))
    assert p.ram_bytes == 0 and p.profile_name == "tiny"


def test_capacity_metrics(tmp_path: Path) -> None:
    metrics = capacity_metrics(tmp_path)
    assert 0.0 < metrics["disk.free_ratio"] <= 1.0
    if "ram.free_ratio" in metrics:
        assert 0.0 <= metrics["ram.free_ratio"] <= 1.0
    fake = capacity_metrics(tmp_path, memory=lambda: (4 * GIB, GIB))
    assert fake["ram.free_ratio"] == 0.25
    assert "ram.free_ratio" not in capacity_metrics(tmp_path, memory=lambda: (None, None))
