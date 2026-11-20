"""Run the user guide's commands in order against a temporary data directory (H1, finding D-1).

    python tools/guide_walkthrough.py [--guide docs/USER-GUIDE.md]

Takes every ``switchyard ...`` line from the ``bash`` blocks of sections 2, 3, 6, 7 and 8, starts the daemon
for ``switchyard api serve``, runs the rest one by one and fails on a non-zero exit or a ``status: failed``
result. Lines with a ``<placeholder>`` cannot run as written and are listed as skipped. At the end the daemon
is stopped the way an operator would (Ctrl+Break on Windows, SIGTERM elsewhere) and must leave no
``api.port`` or ``api.token`` behind (finding D-9).
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import signal
import subprocess  # nosec B404
import sys
import tempfile
import threading
from pathlib import Path

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "USER-GUIDE.md"
SECTIONS = frozenset({"2", "3", "6", "7", "8"})
_HEADING = re.compile(r"## (\d+)\.")
_COMMENT = re.compile(r"\s+#.*$")


def commands(text: str) -> tuple[list[str], list[str]]:
    """(runnable commands, skipped placeholder commands) in guide order."""
    run: list[str] = []
    skipped: list[str] = []
    section, in_block = "", False
    for raw in text.splitlines():
        heading = _HEADING.match(raw)
        if heading:
            section = heading.group(1)
            continue
        if raw.startswith("```"):
            in_block = raw.strip() == "```bash" and not in_block
            continue
        line = _COMMENT.sub("", raw).strip()
        if not in_block or section not in SECTIONS or not line.startswith("switchyard "):
            continue
        (skipped if "<" in line else run).append(line)
    return run, skipped


def _cli(args: list[str]) -> list[str]:
    return [sys.executable, "-m", "switchyard.cli", *args]


def _start_daemon(args: list[str], env: dict[str, str]) -> subprocess.Popen[str]:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0  # type: ignore[attr-defined,unused-ignore]
    proc = subprocess.Popen(  # noqa: S603 # nosec B603
        _cli(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, creationflags=flags
    )
    first: list[str] = []
    reader = threading.Thread(target=lambda: first.append(proc.stdout.readline() if proc.stdout else ""))
    reader.start()
    reader.join(60)
    if not first or "listening" not in first[0]:
        proc.kill()
        raise RuntimeError(f"daemon did not report readiness: {first!r}")
    return proc


def _stop_daemon(proc: subprocess.Popen[str]) -> None:
    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined,unused-ignore]
    else:
        proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(10)


def walkthrough(guide: Path, data_dir: Path) -> list[str]:
    """Run the guide; returns the failures (empty when everything worked)."""
    run, skipped = commands(guide.read_text(encoding="utf-8"))
    env = {**os.environ, "SWITCHYARD_DATA_DIR": str(data_dir), "PYTHONUTF8": "1"}
    failures: list[str] = []
    daemon: subprocess.Popen[str] | None = None
    try:
        for line in run:
            args = shlex.split(line)[1:]
            if args[:2] == ["api", "serve"]:
                daemon = _start_daemon(args, env)
                print(f"ok    {line}")
                continue
            done = subprocess.run(  # noqa: S603 # nosec B603
                _cli(args), capture_output=True, text=True, env=env, timeout=120, check=False
            )
            ok = done.returncode == 0 and "status: failed" not in done.stdout
            print(f"{'ok' if ok else 'FAIL':5} {line}")
            if not ok:
                failures.append(f"{line} -> exit {done.returncode}\n{done.stdout}{done.stderr}")
    finally:
        if daemon is not None:
            _stop_daemon(daemon)
            left = [n for n in ("api.port", "api.token") if (data_dir / n).exists()]
            if left:
                failures.append(f"the stopped daemon left {left} behind")
    for line in skipped:
        print(f"skip  {line}  (placeholder)")
    if not run:
        failures.append("no commands found in the guide")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--guide", type=Path, default=GUIDE)
    args = parser.parse_args(argv)
    data_dir = Path(tempfile.mkdtemp(prefix="sy-guide-"))
    try:
        failures = walkthrough(args.guide, data_dir)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    for failure in failures:
        print(f"\nFAILED: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
