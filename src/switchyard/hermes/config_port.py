"""``HermesConfigPort`` over Hermes's published plugin API (ADR-0005): ``hermes_cli.config`` and
``tools.skills_tool:find_all_skills`` (both listed in Hermes's ``plugin_api.json``)."""

from __future__ import annotations

from typing import Any


class HermesConfigAdapter:
    """``HermesConfigPort`` over Hermes's public API (``hermes_cli.config``, ``tools.skills_tool``)."""

    def get(self, key: str) -> Any:
        from hermes_cli.config import load_config  # type: ignore[import-not-found,unused-ignore]

        node: Any = load_config()
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return node

    def set(self, key: str, value: Any) -> None:
        from hermes_cli.config import load_config, save_config  # type: ignore[import-not-found,unused-ignore]

        config = load_config()
        node = config
        *parents, leaf = key.split(".")
        for part in parents:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[leaf] = value
        save_config(config, merge_existing=True)

    def essential(self) -> frozenset[str]:
        """Hermes's essential skills. Not in the published plugin API, so read defensively."""
        try:
            from agent.skill_utils import ESSENTIAL_SKILLS  # type: ignore[import-not-found,unused-ignore]
        except Exception:
            return frozenset({"hermes-agent"})
        return frozenset(str(s) for s in ESSENTIAL_SKILLS)

    def skills(self) -> list[dict[str, str]]:
        from tools.skills_tool import find_all_skills  # type: ignore[import-not-found,unused-ignore]

        rows: list[dict[str, str]] = find_all_skills(skip_disabled=False)
        return rows
