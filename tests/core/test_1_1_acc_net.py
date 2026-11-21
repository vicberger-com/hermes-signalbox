"""1.1 acceptance security review, network: metadata endpoints in every address form, resolver timeout (S2-1,
S2-8)."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from switchyard import net


@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",  # IPv4 link-local (already refused in 1.1)
        "fe80::1",
        "::ffff:169.254.169.254",
        "fd00:ec2::254",  # AWS IMDS over IPv6
        "64:ff9b::a9fe:a9fe",  # NAT64 well-known prefix (DNS64 answer for 169.254.169.254)
        "2002:a9fe:a9fe::1",  # 6to4
        "::ffff:0:a9fe:a9fe",  # SIIT
        "::169.254.169.254",  # IPv4-compatible
        "168.63.129.16",  # Azure WireServer
        "100.100.100.200",  # Alibaba Cloud metadata
    ],
)
def test_s2_1_metadata_endpoints_are_refused_in_every_form(address: str) -> None:
    assert net._refused_address(address) is not None


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "::1", "10.0.0.5", "192.168.1.10", "172.16.0.1", "8.8.8.8", "2606:4700::1111", "fd12::1"],
)
def test_s2_1_loopback_private_and_public_addresses_stay_allowed(address: str) -> None:
    assert net._refused_address(address) is None  # Q-SY-1.1-2: local services stay reachable


def test_s2_8_a_stalled_resolver_does_not_hold_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def stalled(*_a: object, **_k: object) -> list[object]:
        release.wait(30)
        return []

    monkeypatch.setattr(net.socket, "getaddrinfo", stalled)
    started = time.monotonic()
    try:
        with pytest.raises(OSError):
            net._resolve("slow.example", 443, timeout=0.5)
        assert time.monotonic() - started < 5
    finally:
        release.set()


def test_s2_8_resolution_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    monkeypatch.setattr(net.socket, "getaddrinfo", lambda *_a, **_k: answer)
    assert net._resolve("example.com", 443, timeout=1.0) == ["93.184.216.34"]
