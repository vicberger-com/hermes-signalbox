"""Small helpers shared by the bundled modules (H1 C-13). Stdlib only; no module state."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from switchyard.errors import SwitchyardError


def int_setting(module_id: str, cfg: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    """``cfg[key]`` (or ``default``) as an int in ``[low, high]``; anything else is a configuration error."""
    value = cfg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SwitchyardError(f"[modules.{module_id}] {key} must be an integer from {low} to {high}")
    return value


def default_models_dev_cache() -> Path:
    """Where Hermes keeps its models.dev price cache: ``$HERMES_HOME``, else the platform default."""
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home) / "models_dev_cache.json"
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes" / "models_dev_cache.json"
    return Path.home() / ".hermes" / "models_dev_cache.json"


class StateTables:
    """``_q`` (run SQL on the module's own state) and ``_t`` (its prefixed table name). Needs ``self.ctx``."""

    ctx: Any

    def _q(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = self.ctx.state.execute(sql, params)
        return rows

    def _t(self, name: str) -> str:
        return str(self.ctx.state.table(name))
