"""Switchyard dashboard backend, mounted by Hermes at ``/api/plugins/switchyard/`` (behind dashboard auth).

A thin proxy to Switchyard's loopback control API (``[api] enabled = true``): a fixed list of operations,
validated path parameters, bounded responses. It reads no secrets and holds no state. Grants, installs and
config changes are deliberately not offered here (CLI only).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()
_ID = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
_PANEL = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_ITEM = re.compile(r"[0-9a-f]{16}\Z")
_KINDS = ("health", "usage", "security", "changes")


def _data_dir() -> Path:
    override = os.environ.get("SWITCHYARD_DATA_DIR", "")
    if override:
        return Path(override)
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir("switchyard")


def _call(noun: str, verb: str, params: dict[str, Any]) -> Any:
    from switchyard.api import ApiClient, ApiUnavailable
    from switchyard.errors import SwitchyardError

    try:
        return ApiClient.from_data_dir(_data_dir()).request(noun, verb, params)
    except ApiUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Switchyard API is off: set [api] enabled = true"
        ) from exc
    except SwitchyardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc


def _check(pattern: re.Pattern[str], value: str) -> str:
    if not pattern.match(value):
        raise HTTPException(status_code=400, detail="invalid name")
    return value


@router.get("/modules")
async def modules() -> Any:
    return _call("module", "list", {})


@router.get("/modules/{module_id}")
async def module_show(module_id: str) -> Any:
    return _call("module", "show", {"id": _check(_ID, module_id)})


@router.get("/panel/{module_id}/{panel}")
async def panel(module_id: str, panel: str) -> Any:
    return _call("module", "panel", {"id": _check(_ID, module_id), "panel": _check(_PANEL, panel)})


@router.post("/modules/{module_id}/{verb}")
async def module_lifecycle(module_id: str, verb: str) -> Any:
    if verb not in ("activate", "deactivate"):
        raise HTTPException(status_code=404, detail="unknown action")
    return _call("module", verb, {"id": _check(_ID, module_id)})


@router.get("/report/{kind}")
async def report(kind: str) -> Any:
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail="unknown report")
    return _call("report", "show", {"kind": kind})


@router.get("/inbox")
async def inbox(state: str = "open") -> Any:
    if state not in ("open", "acked", "all"):
        raise HTTPException(status_code=400, detail="invalid state")
    return _call(
        "module", "action", {"id": "inbox", "action": "list", "args": {"state": state, "limit": 200}}
    )


@router.post("/inbox/{item}/ack")
async def inbox_ack(item: str) -> Any:
    return _call("module", "action", {"id": "inbox", "action": "ack", "args": {"id": _check(_ITEM, item)}})


@router.post("/inbox/ack_all")
async def inbox_ack_all() -> Any:
    return _call("module", "action", {"id": "inbox", "action": "ack_all", "args": {}})
