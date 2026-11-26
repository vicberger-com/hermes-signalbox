"""Print one version's section of CHANGELOG.md, for the release body (H1, finding D-24).

    python tools/release_notes.py 1.0.1 > notes.md

Exits 1 when the version has no section or the section is empty, so a release cannot go out without notes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
REPO = "https://github.com/vicberger-com/hermes-signalbox"


def section(text: str, version: str) -> str:
    """The body under ``## [<version>]`` up to the next ``## `` heading or link definitions."""
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |^\[[^\]]+\]: |\Z)", text, re.M | re.S
    )
    if match is None:
        raise LookupError(f"CHANGELOG.md has no section for {version}")
    body = match.group(1).strip()
    if not body:
        raise LookupError(f"the CHANGELOG.md section for {version} is empty")
    return body


def notes(text: str, version: str, previous: str | None) -> str:
    body = section(text, version)
    if previous:
        body += f"\n\nFull changes: {REPO}/compare/v{previous}...v{version}"
    return body + "\n"


def previous_version(text: str, version: str) -> str | None:
    versions: list[str] = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)
    if version in versions and versions.index(version) + 1 < len(versions):
        return versions[versions.index(version) + 1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: release_notes.py <version>", file=sys.stderr)
        return 2
    version = args[0].removeprefix("v")
    text = CHANGELOG.read_text(encoding="utf-8")
    try:
        sys.stdout.write(notes(text, version, previous_version(text, version)))
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
