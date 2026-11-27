"""H5 WP5 (#205-#208, #210): the documentation a first-time user reads.

Each test pins one thing the user-testing findings said was missing: what the dashboard tab shows and where
its limits are, how to read chat and command-line output, a glossary that cannot drift from the labels the
program uses, install commands that name the repository as it is called now, and a documentation link on every
bundled module.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import gen_glossary

from hermes_signalbox import labels

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "docs" / "USER-GUIDE.md").read_text(encoding="utf-8")
MODULES = ROOT / "src" / "hermes_signalbox" / "modules"
REPO = "https://github.com/vicberger-com/hermes-signalbox"


def _section(title: str) -> str:
    found = re.search(rf"^## \d+\. {re.escape(title)}\n(.*?)(?=^## \d+\. |\Z)", GUIDE, re.M | re.S)
    assert found, f"no section {title!r}"
    return found.group(1)


def test_h5_wp5_dashboard_section_explains_each_view_and_what_the_page_cannot_do() -> None:
    text = _section("Dashboard")
    for heading in ("### Modules", "### Inbox", "### Reports"):
        assert heading in text, heading
    for phrase in (
        "Start mode",  # the selector
        "disabled, with the reason",  # a button that cannot work says why
        "Refused:",  # a refused action is shown on its row
        "Open, Acknowledged or All",
        "Raw data (JSON)",
        "Refreshing",
        "What is this page?",
    ):
        assert phrase in text, phrase
    limits = text[text.index("### What the page cannot do") :]
    for word in ("grant", "install", "update", "remove", "settings"):
        assert word in limits.lower(), word
    assert "hermes-signalbox module grant" in limits


def test_h5_wp5_guide_shows_how_to_read_output_and_get_the_raw_data() -> None:
    text = _section("Reading the output, and a glossary")
    assert "0 of 12 modules running · 0 failed · 12 waiting for permissions" in text  # a real summary line
    assert "--json" in text and "json=true" in text
    assert "/signalbox module list" in text
    assert "The model's tools" in text  # the model still gets the payload


def test_h5_wp5_glossary_in_the_guide_is_generated_from_the_labels() -> None:
    assert gen_glossary.current(GUIDE) == gen_glossary.render(), "run: python tools/gen_glossary.py"
    block = gen_glossary.render()
    for group in labels.glossary().values():
        for key, entry in group.items():
            assert f"`{key}`" in block and entry["label"] in block, key
    assert gen_glossary.main(["--check"]) == 0


def test_h5_wp5_glossary_check_fails_on_a_stale_guide(tmp_path: Path) -> None:
    stale = tmp_path / "USER-GUIDE.md"
    stale.write_text(GUIDE.replace("Run on a timer", "Run on a clock"), encoding="utf-8")
    assert gen_glossary.main(["--check", "--file", str(stale)]) == 1
    assert gen_glossary.main(["--file", str(stale)]) == 0  # rewriting repairs it
    assert stale.read_text(encoding="utf-8") == GUIDE


def test_h5_wp5_install_commands_name_the_repository_as_it_is_called_now() -> None:
    for name in ("QUICKSTART.md", "TROUBLESHOOTING.md", "ROADMAP.md", "USER-GUIDE.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "hermes-switchyard" not in text, name
    for name in ("QUICKSTART.md", "TROUBLESHOOTING.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "hermes plugins install vicberger-com/hermes-signalbox" in text, name
    quick = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    assert 'click "Activate"' not in quick and "**Start**" in quick  # the button's real name


def test_h5_wp5_every_bundled_module_links_to_its_documentation_in_this_repository() -> None:
    manifests = sorted(MODULES.glob("*/module.toml"))
    assert len(manifests) == 12
    for path in manifests:
        module = tomllib.loads(path.read_text(encoding="utf-8"))["module"]
        readme = f"src/hermes_signalbox/modules/{path.parent.name}/README.md"
        assert module.get("docs") == f"{REPO}/blob/main/{readme}", path.parent.name
        assert (ROOT / readme).is_file()
        # no upstream is named for a bundled module: none has a recorded reuse of another project's code
        assert "based_on" not in module, path.parent.name


def test_h5_wp5_reference_and_module_docs_describe_the_dashboard_as_it_is() -> None:
    reference = (ROOT / "docs" / "REFERENCE.md").read_text(encoding="utf-8")
    assert "## Dashboard tab" in reference
    for phrase in ("`view`", "`groups`", "`open`", "start mode"):
        assert phrase in reference, phrase
    inbox = (MODULES / "inbox" / "README.md").read_text(encoding="utf-8")
    assert "Open, Acknowledged or All" in inbox


def test_h5_wp5_chat_examples_use_key_value_arguments() -> None:
    # the slash command answers "expected key=value" to a command-line flag, so no chat example may show one
    docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted(MODULES.glob("*/README.md"))]
    for path in docs:
        for example in re.findall(r"`(/signalbox [^`]*)`", path.read_text(encoding="utf-8")):
            assert " --" not in example, f"{path.name}: {example}"
    assert "`/signalbox report show kind=health`" in _section("Notifications and reports")
