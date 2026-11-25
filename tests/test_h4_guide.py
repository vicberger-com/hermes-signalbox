"""H4 WP6: the user guide matches what a clean install on Hermes does (v1.0.2 acceptance findings).

Each test pins one documentation finding to the text that fixes it, so a later edit cannot drop it silently.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "docs" / "USER-GUIDE.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _section(number: int) -> str:
    match = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", GUIDE, flags=re.M | re.S)
    assert match, f"no section {number}"
    return match.group(0)


def test_h4_r1_f1_install_by_owner_and_repository_not_the_catalog_name() -> None:
    install = _section(1)
    assert "hermes plugins install hermes-switchyard" in install  # named as the command to avoid
    assert "different, unrelated project" in install
    assert "vicberger-com/hermes-switchyard" in install and "--ref" in install
    assert "unrelated project" in README and "vicberger-com/hermes-switchyard --ref" in README


def test_h4_r1_f2_custom_source_warning_is_expected() -> None:
    assert "custom (unreviewed) source" in _section(1)


def test_h4_r1_f3_tools_reach_the_model_in_a_new_chat() -> None:
    model = _section(4)
    assert "new chat" in model and "deferred: tools (next session)" in model


def test_h4_r1_f6_a_grant_does_not_start_a_module_in_a_running_hermes() -> None:
    grants = _section(3)
    assert "never starts a module" in grants
    assert "/switchyard module activate <id>" in grants


def test_h4_r1_f13_update_commands_are_chat_only_when_hermes_hosts() -> None:
    updates = _section(7)
    assert "chat-only" in updates and "/switchyard module check_updates" in updates
    assert "/switchyard report show" in _section(6)


def test_h4_doc_1_sections_are_numbered_once_in_order() -> None:
    numbers = [int(n) for n in re.findall(r"^## (\d+)\. ", GUIDE, flags=re.M)]
    assert numbers == list(range(1, len(numbers) + 1))


def test_h4_doc_1_uninstall_disables_first_and_names_every_data_directory() -> None:
    uninstall = _section(9)
    disable = uninstall.index("hermes plugins disable switchyard")
    remove = uninstall.index("hermes plugins remove switchyard")
    assert disable < remove
    assert "hermes gateway restart" in uninstall  # what to do when the gateway did not unload it
    assert "agent-plugin-switchyard-<digest>" in uninstall
    assert "plugin-data/switchyard" in uninstall
    assert "SWITCHYARD_DATA_DIR" in uninstall
