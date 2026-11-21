"""1.1 backlog batch 3: Windows device names in fs.read paths (H1 B-6 #99)."""

from __future__ import annotations

import pytest

from switchyard.errors import SwitchyardError
from switchyard.fsread import check_local_path


@pytest.mark.parametrize(
    "path",
    [
        "C:\\x\\COM¹",
        "C:\\x\\COM²",
        "C:\\x\\LPT³",
        "C:\\x\\LPT¹.txt",
        "C:\\x\\NUL:",
        "C:\\x\\CON:",
        "C:\\x\\con:stream",
        "C:\\x\\NUL. ",
        "C:\\x\\aux .txt",
        "C:\\COM³\\file.txt",
    ],
)
def test_h1_b6_device_aliases_are_refused(path: str) -> None:
    with pytest.raises(SwitchyardError, match="device names"):
        check_local_path(path, windows=True)


@pytest.mark.parametrize(
    "path",
    [
        "C:\\x\\file.txt",
        "C:\\x\\COM10",
        "C:\\x\\console.log",
        "C:\\x\\nullable.json",
        "C:\\x\\file.txt:stream",  # alternate data streams: the grant is the decision (by design)
        "C:\\x\\LPT4x",
    ],
)
def test_h1_b6_ordinary_names_still_pass(path: str) -> None:
    assert str(check_local_path(path, windows=True)) == path
