"""Check and publish the wiki source in docs/wiki/pages (framework: docs/wiki/README.md).

    python tools/wiki_publish.py --check          # links, headers and sources blocks; exit 1 on problems
    python tools/wiki_publish.py --publish DIR    # copy pages into a clone of the wiki repository at DIR

Publishing does not push: review `git -C DIR diff`, then commit and push with your own credentials. The wiki
repository exists only after one page has been created in the GitHub web interface.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

PAGES = Path(__file__).resolve().parent.parent / "docs" / "wiki" / "pages"
LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
HEADER = re.compile(
    r"^> \*\*Type:\*\* [a-z-]+ · \*\*Applies to:\*\* v\d+\.\d+\.\d+ · "
    r"\*\*Last checked:\*\* \d{4}-\d{2}-\d{2} · \*\*Status:\*\* (current|draft|outdated|historical)$",
    re.MULTILINE,
)
SPECIAL = {"_Sidebar.md", "_Footer.md"}


def page_file(title: str) -> str:
    return title.strip().replace(" ", "-") + ".md"


def check() -> list[str]:
    problems: list[str] = []
    names = {p.name for p in PAGES.glob("*.md")}
    for path in sorted(PAGES.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for title in LINK.findall(text):
            if page_file(title) not in names:
                problems.append(f"{path.name}: link to missing page [[{title}]]")
        if path.name in SPECIAL:
            continue
        if not HEADER.search(text):
            problems.append(f"{path.name}: missing or malformed page header")
        if "**Sources:**" not in text:
            problems.append(f"{path.name}: missing sources block")
        if re.search(r"[:/\\]", path.stem):
            problems.append(f"{path.name}: page names may not contain ':', '/' or '\\'")
    return problems


def publish(target: Path) -> None:
    if not (target / ".git").is_dir():
        raise SystemExit(f"{target} is not a git clone of the wiki repository")
    for old in target.glob("*.md"):
        old.unlink()
    for page in PAGES.glob("*.md"):
        shutil.copy2(page, target / page.name)
    print(f"copied {len(list(PAGES.glob('*.md')))} pages into {target}; review, commit and push")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--publish", type=Path, metavar="DIR")
    args = parser.parse_args()
    problems = check()
    for line in problems:
        print(line)
    if args.check:
        print(f"{len(problems)} problem(s) in {len(list(PAGES.glob('*.md')))} pages")
        return 1 if problems else 0
    if problems:
        print("fix the problems above before publishing")
        return 1
    publish(args.publish)
    return 0


if __name__ == "__main__":
    sys.exit(main())
