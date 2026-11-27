"""Shared helpers for tests of ``dashboard/dist/index.js``: run the real file under Node with stand-ins for
the Hermes plugin SDK and React (``tests/fixtures/dashboard_harness.js``) and search the element tree it
renders."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "dashboard" / "dist" / "index.js"
HARNESS = ROOT / "tests" / "fixtures" / "dashboard_harness.js"
BASE = "/api/plugins/signalbox"


def node() -> str:
    found = os.environ.get("SIGNALBOX_NODE") or shutil.which("node")
    if not found:  # a workstation where Node only ships inside the Hermes desktop app
        local = os.environ.get("LOCALAPPDATA", "")
        bundled = (
            sorted(glob.glob(os.path.join(local, "hermes", "tools", "node-*", "node.exe"))) if local else []
        )
        found = bundled[-1] if bundled else None
    if not found:
        pytest.skip("Node.js is not installed")
    return found


def render(**scenario: Any) -> dict[str, Any]:
    """Run the harness on a scenario: ``view`` (component name), ``props``, ``state`` (what the first
    ``useState`` calls return, in order), ``clicks`` and the replies or failures of the page's requests."""
    done = subprocess.run(  # noqa: S603 - a fixed harness file, run with the located node
        [node(), str(HARNESS), str(INDEX)],
        input=json.dumps(scenario),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out: dict[str, Any] = json.loads(done.stdout)
    return out


def loaded(data: Any) -> dict[str, Any]:
    """The state of a finished, successful load."""
    return {"loading": False, "data": data, "error": None, "at": 1_800_000_000_000}


def find_all(tree: Any, test: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(tree, list):
        for child in tree:
            found += find_all(child, test)
    elif isinstance(tree, dict):
        if test(tree):
            found.append(tree)
        found += find_all(tree["children"], test)
    return found


def text_of(tree: Any) -> str:
    if isinstance(tree, str):
        return tree
    if isinstance(tree, list):
        return "".join(text_of(c) for c in tree)
    return text_of(tree["children"]) if isinstance(tree, dict) else ""


def by_marker(tree: Any, marker: str) -> dict[str, Any]:
    """The one element carrying ``data-sy="<marker>"``."""
    [hit] = find_all(tree, lambda n: n["props"].get("data-sy") == marker)
    return hit


def markers(tree: Any, prefix: str) -> list[str]:
    hits = find_all(tree, lambda n: str(n["props"].get("data-sy", "")).startswith(prefix))
    return [str(n["props"]["data-sy"]) for n in hits]
