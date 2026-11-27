"""Repository review of 2026-11-26 (operator request): the hand-written quick start and troubleshooting pages
showed commands that the command line does not have, and a grant command that silently granted one
permission out of several.

D-1  An option given twice (``--capability a --capability b``) kept the last value and dropped the rest
     without a word, at the terminal and in chat. It is now refused.
D-2  Every Signalbox command shown in QUICKSTART.md and TROUBLESHOOTING.md is parsed here with the real
     parser, so a page cannot show a command that does not exist.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from hermes_signalbox.cli import _parser, main
from hermes_signalbox.core import Core
from hermes_signalbox.hermes import HermesAdapter
from hermes_signalbox.ops import OPERATIONS

DOCS = Path(__file__).resolve().parents[1] / "docs"
PAGES = ("QUICKSTART.md", "TROUBLESHOOTING.md")
PREFIXES = ("hermes -p default signalbox ", "hermes-signalbox ", "/signalbox ")


def test_d1_the_command_line_refuses_an_option_given_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--data-dir", str(tmp_path), "module", "grant", "inbox"]
    with pytest.raises(SystemExit) as stop:
        main([*argv, "--capability", "core.read", "--capability", "ui.panel"])
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "--capability was given more than once" in err and "one command for each" in err


def test_d1_one_value_and_yes_no_flags_still_work() -> None:
    args = _parser().parse_args(["module", "update", "m1", "--ref", "a" * 40, "--accept-wider"])
    assert (args.id, args.ref, args.accept_wider, args.allow_downgrade) == ("m1", "a" * 40, True, False)
    assert _parser().parse_args(["audit", "tail", "--n", "5"]).n == 5
    assert _parser().parse_args(["audit", "tail"]).n is None


@pytest.mark.parametrize(
    "words",
    [
        "module grant inbox --capability core.read --capability ui.panel",
        "module grant inbox capability=core.read capability=ui.panel",
        "module grant inbox --capability=core.read capability=ui.panel",
        "module show inbox id=other",
    ],
)
def test_d1_chat_refuses_a_value_given_twice(tmp_path: Path, words: str) -> None:
    with Core(data_dir=tmp_path, hosting=True) as core:
        adapter = HermesAdapter.__new__(HermesAdapter)
        adapter.core = core
        reply = adapter.command(words)
        assert reply.startswith("error: ") and "more than once" in reply, reply
        actions = [r["action"] for r in core.run("audit", "tail", {"n": 20}, actor="cli")]
        assert "policy.granted" not in actions  # nothing was granted on the way


def _commands(page: str) -> list[tuple[int, str]]:
    found, fenced = [], False
    for number, line in enumerate((DOCS / page).read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("```"):
            fenced = not fenced
            continue
        text = line.strip()
        if fenced and text.startswith(PREFIXES):
            found.append((number, text))
    return found


def _argv(command: str) -> list[str]:
    for prefix in PREFIXES:
        if command.startswith(prefix):
            command = command[len(prefix) :]
    command = command.split(" | ")[0].split(" #")[0]
    command = re.sub(r"<[a-z_-]+>", "placeholder", command)
    return shlex.split(command)


@pytest.mark.parametrize("page", PAGES)
def test_d2_every_command_shown_in_the_page_exists(page: str) -> None:
    commands = _commands(page)
    assert len(commands) >= 10, f"{page}: the command blocks were not found"
    problems = []
    for number, command in commands:
        argv = _argv(command)
        try:
            args = _parser().parse_args(argv)
        except SystemExit:
            problems.append(f"{page}:{number}: {command}")
            continue
        if args.noun == "module" and args.verb == "action" and command.startswith("hermes-signalbox"):
            continue
        assert args.noun in ("api", "version") or (args.noun, args.verb) in OPERATIONS
    assert not problems, "commands the parser refuses:\n" + "\n".join(problems)


@pytest.mark.parametrize("page", PAGES)
def test_d2_the_pages_do_not_teach_what_breaks_an_install(page: str) -> None:
    text = (DOCS / page).read_text(encoding="utf-8")
    assert "[api] enabled = true' >>" not in text  # one line is not valid TOML and breaks config.toml
    assert "secrets add" not in text and "module run " not in text  # neither exists
    assert not re.search(r"^signalbox module", text, flags=re.MULTILINE)  # the command is hermes-signalbox


def test_d2_the_quick_start_grants_every_required_permission_of_the_bundled_modules() -> None:
    import tomllib

    text = (DOCS / "QUICKSTART.md").read_text(encoding="utf-8")
    shown = set(
        re.findall(r"signalbox module grant ([a-z_]+) --capability ([a-z_.]+)$", text, flags=re.MULTILINE)
    )
    modules = Path(__file__).resolve().parents[1] / "src" / "hermes_signalbox" / "modules"
    needed = set()
    for manifest in sorted(modules.glob("*/module.toml")):
        caps = tomllib.loads(manifest.read_text(encoding="utf-8")).get("capabilities", {})
        for capability in set(caps.get("request", [])) - set(caps.get("optional", [])):
            needed.add((manifest.parent.name, capability))
    assert len(needed) >= 30
    assert shown == needed, f"missing {sorted(needed - shown)}, not required {sorted(shown - needed)}"
