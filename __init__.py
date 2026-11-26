"""Hermes plugin shim for git installs (``hermes plugins install``): exposes
``hermes_signalbox.hermes.register``.

A pip install provides the ``hermes_signalbox`` package directly (entry point ``hermes_agent.plugins``). A git
install places this repository in the plugins directory without installing the package (``python_runtime:
external`` in ``plugin.yaml``), so ``src`` is put first on the path: this directory's own code runs, never
another installed copy of a different version (1.1 S-3).
The package itself has no runtime dependencies (ADR-0001).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if (_SRC / "hermes_signalbox" / "__init__.py").is_file():
    if str(_SRC) in sys.path:
        sys.path.remove(str(_SRC))
    sys.path.insert(0, str(_SRC))

from hermes_signalbox.hermes import register  # noqa: E402 - after the path set-up above

__all__ = ["register"]
