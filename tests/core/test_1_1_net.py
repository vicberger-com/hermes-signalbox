"""1.1 backlog batch 4: module headers cannot override Host (H1 B-22 #111).

The allow-list checks the URL's host; a module-set ``Host`` header would send the request to another virtual
host on the same address. The broker drops it (any case) and the URL's host is what goes on the wire.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from switchyard import net


class _AllowAll:
    def require_host(self, module_id: str, host: str) -> None:
        pass


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(self, **kw: Any) -> None:
        self.records.append(kw)


class _Resp:
    status = 200
    headers: ClassVar[dict[str, str]] = {}

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: Any) -> None:
        pass

    def read(self, n: int = -1) -> bytes:
        return b""


@pytest.mark.parametrize("name", ["Host", "host", "HOST", " Host"])
def test_h1_b22_module_host_header_is_dropped(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    def fake_open(req: Any, timeout: float) -> _Resp:
        sent.append(req)
        return _Resp()

    monkeypatch.setattr(net._OPENER, "open", fake_open)
    broker = net.NetBroker(_AllowAll(), _Audit())  # type: ignore[arg-type]
    broker.request("demo", "GET", "http://allowed.example/x", headers={name: "internal.example", "X-A": "1"})
    req = sent[0]
    names = {k.strip().lower() for k in req.headers} | {k.strip().lower() for k in req.unredirected_hdrs}
    assert "host" not in names
    assert req.host == "allowed.example"
    assert req.get_header("X-a") == "1"  # other headers still pass
