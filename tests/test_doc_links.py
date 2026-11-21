"""H1 close (section 5): relative links in the documentation point at files that exist."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```.*?^```", re.S | re.M)


def _docs() -> list[Path]:
    files = [*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"), *(ROOT / "src").rglob("README.md")]
    # wiki templates hold `<link>` placeholders by design
    return sorted(p for p in files if ".venv" not in p.parts and "templates" not in p.parts)


def test_h1_relative_doc_links_resolve() -> None:
    broken = []
    for doc in _docs():
        text = FENCE.sub("", doc.read_text(encoding="utf-8"))
        for target in LINK.findall(text):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue  # external URL, mailto or in-page anchor
            path = target.split("#", 1)[0]
            if path and not (doc.parent / path).exists():
                broken.append(f"{doc.relative_to(ROOT).as_posix()}: {target}")
    assert broken == []
