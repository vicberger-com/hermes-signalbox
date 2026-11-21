"""Outbound network broker: the ``net.outbound`` capability (``ctx.net``; ADR-0010).

``ctx.net.request(method, url, json=..., headers=..., timeout=...)`` makes one HTTP(S) request for a module
granted ``net.outbound`` to a host listed in its manifest's ``net_hosts`` (``host`` or ``host:port``, exact
match). No redirects are followed (a redirect could leave the allow-list), proxies from the environment are
ignored, the response body is capped, and each request is audited with host, method and status only: URLs
paths, headers and bodies can carry secrets and are never recorded.
"""

from __future__ import annotations

import http.client
import json as jsonlib
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from switchyard.capabilities import AuditSink, PolicyEngine
from switchyard.errors import SwitchyardError

MAX_BODY_OUT = 1_000_000
MAX_BODY_IN = 4_000_000
MAX_TIMEOUT_S = 120.0
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    truncated: bool

    def json(self) -> Any:
        try:
            return jsonlib.loads(self.body)
        except ValueError as exc:
            raise SwitchyardError("response is not JSON") from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _read_until(resp: Any, deadline: float) -> bytes:
    """Read at most ``MAX_BODY_IN + 1`` bytes, in chunks, within a total deadline (a trickling server cannot
    hold the call beyond ``timeout``; M11 review)."""
    chunks: list[bytes] = []
    size = 0
    while size <= MAX_BODY_IN:
        if time.monotonic() > deadline:
            raise TimeoutError("total timeout")
        reader = getattr(resp, "read1", None) or resp.read  # read1: what has arrived, not a full block
        chunk = reader(min(65536, MAX_BODY_IN + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


class NetBroker:
    def __init__(self, policy: PolicyEngine, audit: AuditSink) -> None:
        self._policy = policy
        self._audit = audit

    def for_module(self, module_id: str) -> ModuleNet:
        return ModuleNet(self, module_id)

    def request(
        self,
        module_id: str,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> Response:
        method = method.upper()
        if method not in METHODS:
            raise SwitchyardError(f"method must be one of {list(METHODS)}")
        try:  # malformed ports and brackets raise ValueError in urllib (M11 review)
            parts = urllib.parse.urlsplit(url)
            port = parts.port
        except ValueError:
            raise SwitchyardError("url is malformed") from None
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise SwitchyardError("url must be http(s)://host[:port]/path without credentials")
        host = parts.hostname.lower() + (f":{port}" if port else "")
        self._policy.require_host(module_id, host)
        data = None
        # No CR/LF, and no Host: the URL's host is the one the allow-list checked (H1 B-22).
        all_headers = {
            k: v
            for k, v in (headers or {}).items()
            if "\n" not in k + v and "\r" not in k + v and k.strip().lower() != "host"
        }
        if json is not None:
            data = jsonlib.dumps(json).encode("utf-8")
            if len(data) > MAX_BODY_OUT:
                raise SwitchyardError("request body too large")
            all_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, method=method, headers=all_headers)  # noqa: S310 - scheme checked
        status = 0
        deadline = time.monotonic() + min(max(timeout, 0.5), MAX_TIMEOUT_S)
        try:
            with _OPENER.open(req, timeout=min(max(timeout, 0.5), MAX_TIMEOUT_S)) as resp:  # nosec B310
                status = resp.status
                raw = _read_until(resp, deadline)
                expected = resp.headers.get("Content-Length")
                if expected and expected.isdigit() and len(raw) < min(int(expected), MAX_BODY_IN + 1):
                    raise http.client.IncompleteRead(raw)  # closed early: not a complete answer (M11 review)
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = _read_until(exc, deadline) if exc.fp is not None else b""
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            self._record(module_id, host, method, type(exc).__name__)
            raise SwitchyardError(f"request to {host} failed: {type(exc).__name__}") from None
        self._record(module_id, host, method, str(status))
        return Response(status, raw[:MAX_BODY_IN].decode("utf-8", errors="replace"), len(raw) > MAX_BODY_IN)

    def _record(self, module_id: str, host: str, method: str, result: str) -> None:
        self._audit.append(
            actor="core",
            action="net.request",
            module=module_id,
            detail={"host": host, "method": method, "result": result},
        )


class ModuleNet:
    __slots__ = ("_broker", "_module_id")

    def __init__(self, broker: NetBroker, module_id: str) -> None:
        self._broker = broker
        self._module_id = module_id

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        return self._broker.request(self._module_id, method, url, **kwargs)
