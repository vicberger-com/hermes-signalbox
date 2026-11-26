"""Host profiler (spec section 3, Host profiler).

Reads CPU count, physical and available RAM, free disk in the data directory, and a GPU hint, then picks a
capacity profile. No subprocess and no network: RAM comes from ``GlobalMemoryStatusEx`` (Windows),
``/proc/meminfo`` (Linux) or ``sysctlbyname`` through ``ctypes`` (macOS). GPU detection is best effort
(``/proc/driver/nvidia/version`` on Linux); ``net_class`` is ``unknown`` because probing the network would be
an outbound call the core does not make (Q&A B9).

Profiles: ``tiny`` (< 4 GiB RAM or < 2 CPUs), ``laptop`` (< 16 GiB), ``workstation`` (< 64 GiB), else
``server``.
A configured ``host.profile`` other than ``auto`` overrides the result.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hermes_signalbox.config import HOST_PROFILES
from hermes_signalbox.errors import ConfigError

GIB = 1024**3
MemoryReader = Callable[[], tuple[int | None, int | None]]


@dataclass(frozen=True)
class HostProfile:
    platform: str
    cpu_count: int
    ram_bytes: int
    disk_free_bytes: int
    gpu: str | None
    net_class: str
    profile_name: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify(cpu_count: int, ram_bytes: int) -> str:
    if ram_bytes < 4 * GIB or cpu_count < 2:
        return "tiny"
    if ram_bytes < 16 * GIB:
        return "laptop"
    if ram_bytes < 64 * GIB:
        return "workstation"
    return "server"


def parse_meminfo(text: str) -> tuple[int | None, int | None]:
    """(MemTotal, MemAvailable) in bytes from ``/proc/meminfo`` text."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key.strip()] = int(parts[0]) * 1024
    return values.get("MemTotal"), values.get("MemAvailable")


def _memory_windows() -> tuple[int | None, int | None]:  # pragma: no cover - platform specific
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]  # fmt: skip

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009 - windll exists only on Windows; keeps mypy portable
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def _memory_darwin() -> tuple[int | None, int | None]:  # pragma: no cover - platform specific
    libc = ctypes.CDLL(None)
    value = ctypes.c_uint64(0)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    if libc.sysctlbyname(b"hw.memsize", ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
        return None, None
    return int(value.value), None


def _memory_linux() -> tuple[int | None, int | None]:  # pragma: no cover - platform specific
    try:
        return parse_meminfo(Path("/proc/meminfo").read_text(encoding="ascii"))
    except OSError:
        return None, None


def read_memory() -> tuple[int | None, int | None]:
    """(total, available) physical memory in bytes; ``None`` where unknown."""
    try:
        if sys.platform == "win32":
            return _memory_windows()
        if sys.platform == "darwin":
            return _memory_darwin()
        return _memory_linux()
    except (OSError, AttributeError):  # pragma: no cover - defensive
        return None, None


def read_gpu() -> str | None:
    if Path("/proc/driver/nvidia/version").exists():  # pragma: no cover - needs an NVIDIA Linux host
        return "nvidia"
    return None


def profile(
    *,
    data_dir: Path,
    override: str = "auto",
    cpu_count: Callable[[], int | None] = os.cpu_count,
    memory: MemoryReader = read_memory,
    gpu: Callable[[], str | None] = read_gpu,
) -> HostProfile:
    if override not in HOST_PROFILES:
        raise ConfigError(f"host.profile must be one of {sorted(HOST_PROFILES)}")
    cpus = cpu_count() or 1
    total, _ = memory()
    ram = total or 0
    name = classify(cpus, ram) if override == "auto" else override
    return HostProfile(sys.platform, cpus, ram, shutil.disk_usage(data_dir).free, gpu(), "unknown", name)


def capacity_metrics(data_dir: Path, *, memory: MemoryReader = read_memory) -> dict[str, float]:
    """Metrics for capacity triggers (``Scheduler.observe``): ``disk.free_ratio`` and, where known,
    ``ram.free_ratio``."""
    usage = shutil.disk_usage(data_dir)
    metrics = {"disk.free_ratio": usage.free / usage.total if usage.total else 0.0}
    total, available = memory()
    if total and available is not None:
        metrics["ram.free_ratio"] = available / total
    return metrics
