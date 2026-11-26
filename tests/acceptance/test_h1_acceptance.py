"""H1 acceptance (docs/qa/15-h1-prework.md section 5).

Each H1 must ID is fixed with a regression test named ``test_h1_<id>_...`` written before the fix, in the test
file of the component it touches (the public surface it drives). This file checks that the mapping is complete
against the findings index, and covers the must IDs whose surface is a workflow file (D-3, D-4, D-6), which no
unit test can drive.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "docs" / "qa" / "h1" / "findings-index.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def _rows() -> list[list[str]]:
    rows = []
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 7 and re.fullmatch(r"[A-D]-\d+", cells[0]):
            rows.append(cells)
    return rows


def _test_names() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "tests").rglob("test_*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_h1_"):
                names.add(node.name)
    return names


def _workflow(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def _script(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def test_h1_every_must_id_has_a_regression_test_and_a_status() -> None:
    names = _test_names()
    must = [r for r in _rows() if r[3] == "H1 must"]
    assert len(must) == 35
    missing = [
        r[0]
        for r in must
        if not any(n.startswith(f"test_h1_{r[0].lower().replace('-', '')}_") for n in names)
    ]
    assert missing == []
    assert [r[0] for r in must if not r[6].startswith("fixed in #")] == []


def test_h1_every_finding_is_dispositioned_and_backlog_has_an_issue() -> None:
    rows = _rows()
    assert [r[0] for r in rows if r[6] == "open"] == []
    backlog = [r for r in rows if r[3] == "Backlog 1.1"]
    status = re.compile(r"backlog #\d+|fixed in #\d+ \(backlog #\d+\)")
    assert backlog and all(status.fullmatch(r[6]) for r in backlog)
    # A fixed backlog finding is published (Q-SY-H1-3).
    assert [r[0] for r in backlog if r[6].startswith("fixed") and r[5] == "private until fixed"] == []


def test_h1_d3_release_publishes_only_a_verified_annotated_tag_on_main() -> None:
    jobs = _workflow(RELEASE)["jobs"]
    verify = _script(jobs["verify"])
    # actions/checkout rewrites a pushed tag as a lightweight ref, so the real tag object is fetched first
    fetch = 'git fetch --force --no-tags origin "refs/tags/$GITHUB_REF_NAME:refs/tags/$GITHUB_REF_NAME"'
    assert verify.index(fetch) < verify.index("cat-file -t")
    assert 'merge-base --is-ancestor "$GITHUB_SHA" origin/main' in verify
    assert 'cat-file -t "refs/tags/$GITHUB_REF_NAME")" = "tag"' in verify
    assert '[ "v$version" = "$GITHUB_REF_NAME" ]' in verify
    release = jobs["release"]
    assert release["needs"] == "verify" and release["environment"] == "release"


def test_h1_d4_ci_runs_a_pinned_real_hermes_and_requires_it() -> None:
    jobs = _workflow(CI)["jobs"]
    job = jobs["hermes-integration"]
    assert re.fullmatch(r"[0-9a-f]{40}", job["env"]["HERMES_REF"])
    assert "uv sync --frozen" in _script(job)
    step = job["steps"][-1]
    assert step["env"]["SIGNALBOX_REQUIRE_HERMES"] == "1" and "tests/integration" in step["run"]
    assert "hermes-integration" in jobs["ci-required"]["needs"]


def test_h1_d6_ci_builds_checks_and_installs_the_artifacts() -> None:
    package = _script(_workflow(CI)["jobs"]["package"])
    assert "python -m build" in package and "tools/check_dist.py dist" in package
    tool = (ROOT / "tools" / "check_dist.py").read_text(
        encoding="utf-8"
    )  # clean install + CLI smoke live here
    assert "venv.EnvBuilder(with_pip=False, clear=True)" in tool and 'run("version")' in tool
    shipped = _script(_workflow(RELEASE)["jobs"]["release"])
    assert 'cyclonedx-py environment "$RUNNER_TEMP/shipped/bin/python"' in shipped
