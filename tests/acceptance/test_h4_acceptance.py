"""H4 acceptance: traceability from the phase Q&A to the regression tests.

Each finding's regression test lives in its component test file. This file checks three things: every
finding in the disposition table (section 6 of ``docs/qa/18-h4-prework.md``) is ``fixed`` with a pull request
number, every work package in section 4 has a disposition, and every finding has at least one
``test_h4_<id>_`` test function somewhere under ``tests/``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA = (ROOT / "docs" / "qa" / "18-h4-prework.md").read_text(encoding="utf-8")


def _section(title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}.*?(?=^## |\Z)", QA, flags=re.M | re.S)
    assert match, title
    return match.group(0)


def _dispositions() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for line in _section("6. Dispositions").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0] not in ("ID", "---"):
            rows[cells[0]] = (cells[2], cells[3])
    return rows


def _test_names() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names.update(n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    return names


def _prefixes(finding: str) -> tuple[str, ...]:
    slug = finding.lower().replace("-", "_")  # R1-F9 -> r1_f9, H4-N1 -> h4_n1, doc-1 -> doc_1
    short = slug.removeprefix("r1_").removeprefix("h4_")  # WP1/WP2 tests were named test_h4_f8_, test_h4_n1_
    return (f"test_h4_{slug}_", f"test_h4_{short}_")


def test_h4_every_finding_is_fixed_with_a_pull_request() -> None:
    rows = _dispositions()
    assert len(rows) == 16, sorted(rows)
    for finding, (status, pr) in rows.items():
        assert status == "fixed", finding
        assert re.fullmatch(r"#\d+", pr), (finding, pr)


def test_h4_every_work_package_finding_has_a_disposition() -> None:
    planned = set(re.findall(r"\b(R1-F\d+|H4-N\d+|doc-\d+)\b", _section("4. Work packages")))
    assert planned and planned <= set(_dispositions())


def test_h4_every_finding_has_a_regression_test() -> None:
    names = _test_names()
    missing = [f for f in _dispositions() if not any(n.startswith(_prefixes(f)) for n in names)]
    assert missing == []
