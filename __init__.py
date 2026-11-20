"""Hermes plugin shim for git installs (``hermes plugins install``): exposes ``switchyard.hermes.register``.

A pip install provides the ``switchyard`` package directly (entry point ``hermes_agent.plugins``). A git
install places this repository in the plugins directory without installing the package, so ``src`` is added
to the path.
The package itself has no runtime dependencies (ADR-0001).
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import switchyard  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from switchyard.hermes import register

__all__ = ["register"]
