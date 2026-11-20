"""H1 D-1: the user guide's commands succeed as written (``tools/guide_walkthrough.py``)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "guide_walkthrough.py"


def _tool() -> object:
    spec = importlib.util.spec_from_file_location("guide_walkthrough", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_h1_d1_guide_commands_run_as_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)
    tool = _tool()
    failures = tool.walkthrough(tool.GUIDE, tmp_path / "data")  # type: ignore[attr-defined]
    assert failures == []


def test_h1_guide_parser_takes_only_runnable_lines() -> None:
    tool = _tool()
    text = (
        "## 1. Install\n```bash\nswitchyard version\n```\n"
        "## 2. First run\n```bash\nswitchyard api serve   # step 0\nswitchyard module show <id>\n"
        "hermes plugins list\n```\nswitchyard outside a block\n"
    )
    run, skipped = tool.commands(text)  # type: ignore[attr-defined]
    assert run == ["switchyard api serve"] and skipped == ["switchyard module show <id>"]
