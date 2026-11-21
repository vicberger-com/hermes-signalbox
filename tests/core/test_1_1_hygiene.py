"""1.1 backlog batch 12: coding-practice findings (H1 B-25 #113)."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from switchyard import host_t2, host_t2_child, ops
from switchyard.errors import SwitchyardError
from switchyard.ops import UsageError


class _Action:
    def __init__(self, handler: Any, params: dict[str, Any]) -> None:
        self.name = "act"
        self.handler = handler
        self.params = params


def test_h1_b25_a_type_error_inside_an_action_is_a_failure_not_a_missing_argument() -> None:
    def handler(text: str) -> Any:
        raise TypeError("helper() missing 1 required positional argument: 'x'")  # a bug inside the action

    with pytest.raises(SwitchyardError, match="failed: TypeError") as info:
        ops.call_action_handler(_Action(handler, {}), {"text": "hi"})
    assert not isinstance(info.value, UsageError)


def test_h1_b25_a_missing_argument_is_still_a_usage_error() -> None:
    def handler(text: str, count: int) -> Any:
        return text * count

    with pytest.raises(UsageError, match="missing argument"):
        ops.call_action_handler(_Action(handler, {}), {"text": "hi"})
    assert ops.call_action_handler(_Action(handler, {}), {"text": "a", "count": 2}) == "aa"


def test_h1_b25_a_failed_t2_shutdown_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    module = host_t2.T2Module.__new__(host_t2.T2Module)
    module._manifest = SimpleNamespace(id="ext")  # type: ignore[assignment]
    calls: list[str] = []

    def call(method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        calls.append(method)
        if method == "shutdown":
            raise subprocess.TimeoutExpired("child", 5)
        return None

    module._call = call  # type: ignore[method-assign]
    module._channel = object()  # type: ignore[assignment]
    module._proc = None
    module.kill = lambda: calls.append("kill")  # type: ignore[method-assign]
    module.deactivate()
    assert calls == ["deactivate", "shutdown", "kill"]
    assert "did not shut down cleanly (TimeoutExpired)" in capsys.readouterr().err
    assert module.shutdown_error == "TimeoutExpired"


def test_h1_b25_updates_is_split_and_keeps_its_names() -> None:
    from switchyard import gitfetch, sbom, updates

    assert updates.GitFetcher is gitfetch.GitFetcher and updates.patch_notes is sbom.patch_notes
    assert updates.inventory is sbom.inventory and updates.git_usable is gitfetch.git_usable


def test_h1_b25_child_host_takes_its_channel_without_a_lazy_wrapper() -> None:
    assert not hasattr(host_t2_child, "_Lazy")
    host = host_t2_child.ChildHost()
    port: Any = object()
    host.attach(port)
    assert host._parent is port
