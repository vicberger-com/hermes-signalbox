"""ADR-0016, trust but validate: the principle stays stated where the work is planned and judged, and the
gap analysis keeps naming every bundled module until the gaps are closed."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADR = "adr/0016-trust-but-validate.md"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_adr_0016_states_the_four_questions_and_the_five_parts() -> None:
    adr = _read("docs/" + ADR)
    for question in ("Is it safe and secure?", "Was it done?", "Was it done right?", "What should improve?"):
        assert question in adr
    for part in ("| Configuration |", "| Controls |", "| Status |", "| Results |", "| Log and report |"):
        assert part in adr
    assert "The security model does not change" in adr


@pytest.mark.parametrize(
    "relative", ["AGENTS.md", "README.md", "docs/DESIGN.md", "docs/BUILD-PLAN.md", "docs/ROADMAP.md"]
)
def test_the_principle_is_linked_from_where_work_is_planned_and_judged(relative: str) -> None:
    assert "0016-trust-but-validate.md" in _read(relative)


def test_the_prework_template_asks_the_validation_question_and_the_gate_exists() -> None:
    assert "| 13 | Validation (ADR-0016)" in _read("docs/qa/TEMPLATE-module-prework.md")
    assert "| Validation | Every function added or changed answers pre-work question 13" in _read(
        "docs/BUILD-PLAN.md"
    )


def test_the_gap_analysis_names_every_bundled_module() -> None:
    gap = _read("docs/qa/20-validation-gap.md")
    modules = sorted(
        p.name
        for p in (ROOT / "src" / "hermes_signalbox" / "modules").iterdir()
        if (p / "module.toml").is_file()
    )
    assert len(modules) == 12
    for module in modules:
        assert f"| {module} |" in gap, module
