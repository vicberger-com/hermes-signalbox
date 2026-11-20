"""H1 D-6, D-24: release tooling (wheel content check, release notes from the changelog)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from check_dist import EXPECTED, diff, expected_files, project_version, wheel_files
from release_notes import CHANGELOG, main, notes, previous_version, section

TEXT = """# Changelog

## [Unreleased]

## [1.0.1] - 2026-11-21

### Security
- Fixed things.

## [1.0.0] - 2026-11-20

### Added
- First.

## [0.9.0] - 2026-11-19

[Unreleased]: https://example/compare/v1.0.1...HEAD
[1.0.1]: https://example/compare/v1.0.0...v1.0.1
"""


def test_h1_d24_release_notes_come_from_the_changelog() -> None:
    assert section(TEXT, "1.0.1") == "### Security\n- Fixed things."
    assert previous_version(TEXT, "1.0.1") == "1.0.0" and previous_version(TEXT, "0.9.0") is None
    assert notes(TEXT, "1.0.1", "1.0.0").endswith("compare/v1.0.0...v1.0.1\n")
    for missing in ("2.0.0", "0.9.0"):  # no section, empty section
        with pytest.raises(LookupError):
            section(TEXT, missing)


def test_h1_d24_release_notes_cli(capsys: pytest.CaptureFixture[str]) -> None:
    current = CHANGELOG.read_text(encoding="utf-8")
    assert "[Unreleased]: https://github.com/vicberger-com/hermes-switchyard/compare/" in current
    assert main(["v1.0.0"]) == 0 and "### Added" in capsys.readouterr().out
    assert main(["9.9.9"]) == 1 and "no section" in capsys.readouterr().err
    assert main([]) == 2


def test_h1_d5_wheel_list_is_checked(tmp_path: Path) -> None:
    wheel = tmp_path / "hermes_switchyard-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("switchyard/__init__.py", "")
        zf.writestr("hermes_switchyard-9.9.9.dist-info/METADATA", "")
    files = wheel_files(wheel)
    assert files == ["hermes_switchyard.dist-info/METADATA", "switchyard/__init__.py"]
    assert diff(files, ["switchyard/__init__.py", "switchyard/py.typed"]) == [
        "unexpected in wheel: hermes_switchyard.dist-info/METADATA",
        "missing from wheel: switchyard/py.typed",
    ]
    expected = expected_files(EXPECTED)
    for required in ("switchyard/py.typed", "switchyard/_plugin/plugin.yaml",
                     "switchyard/_plugin/dashboard/manifest.json"):  # fmt: skip
        assert required in expected
    assert project_version().count(".") == 2
