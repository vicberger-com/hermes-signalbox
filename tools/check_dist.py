"""Check built distributions: the wheel's file list, a clean install, and a CLI smoke test (H1 D-5, D-6).

    python tools/check_dist.py dist [--venv DIR]

Compares the wheel's files with ``tools/wheel_files.txt`` (version-independent: the ``*.dist-info`` directory
name is normalised), checks an sdist exists, installs the wheel with no dependencies into a fresh virtual
environment without pip, and runs ``hermes-signalbox version``, ``module list`` and ``config show`` there
against a
temporary data directory. ``--venv`` keeps the environment (the release SBOM is generated from it, so it lists
what ships, not the build tools).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "tools" / "wheel_files.txt"
_DIST_INFO = re.compile(r"^hermes_signalbox-[^/]+\.dist-info/")


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def wheel_files(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    return sorted(_DIST_INFO.sub("hermes_signalbox.dist-info/", n) for n in names)


def expected_files(path: Path = EXPECTED) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return sorted(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def diff(actual: list[str], expected: list[str]) -> list[str]:
    a, e = set(actual), set(expected)
    return [f"unexpected in wheel: {n}" for n in sorted(a - e)] + [
        f"missing from wheel: {n}" for n in sorted(e - a)
    ]


def _bin(env: Path, name: str) -> Path:
    return env / ("Scripts" if os.name == "nt" else "bin") / (name + (".exe" if os.name == "nt" else ""))


def smoke(wheel: Path, env: Path) -> list[str]:
    """Install ``wheel`` into a new environment at ``env`` and run the CLI. Returns problems."""
    venv.EnvBuilder(with_pip=False, clear=True).create(env)
    python = _bin(env, "python")
    subprocess.run(  # noqa: S603 # nosec B603
        [sys.executable, "-m", "pip", "--python", str(python), "install", "--no-deps", "--no-index",
         "--quiet", str(wheel)],
        check=True,
    )  # fmt: skip
    cli = _bin(env, "hermes-signalbox")
    problems: list[str] = []
    data = Path(tempfile.mkdtemp(prefix="sy-smoke-"))
    run_env = {**os.environ, "SIGNALBOX_DATA_DIR": str(data)}
    try:

        def run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(  # noqa: S603 # nosec B603
                [str(cli), *args], capture_output=True, text=True, env=run_env, timeout=120, check=False
            )

        version = run("version")
        if version.returncode != 0 or version.stdout.strip() != project_version():
            problems.append(
                f"hermes-signalbox version printed {version.stdout.strip()!r} (exit {version.returncode})"
            )
        listed = run("--json", "module", "list")
        bundled = sorted(
            p.parent.name for p in (ROOT / "src" / "hermes_signalbox" / "modules").glob("*/module.toml")
        )
        try:
            ids = sorted(row["id"] for row in json.loads(listed.stdout))
        except (ValueError, TypeError, KeyError):
            ids = []
        if listed.returncode != 0 or ids != bundled:
            problems.append(
                f"module list from the wheel: {ids} (exit {listed.returncode}); expected {bundled}"
            )
        shown = run("config", "show")
        if shown.returncode != 0 or f"data_dir: {data}" not in shown.stdout:
            problems.append(f"config show failed (exit {shown.returncode}): {shown.stdout}{shown.stderr}")
    finally:
        shutil.rmtree(data, ignore_errors=True)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist", type=Path)
    parser.add_argument("--venv", type=Path, default=None, help="keep the smoke-test environment here")
    args = parser.parse_args(argv)
    wheels = sorted(args.dist.glob("hermes_signalbox-*.whl"))
    sdists = sorted(args.dist.glob("hermes_signalbox-*.tar.gz"))
    problems: list[str] = []
    if len(wheels) != 1 or len(sdists) != 1:
        problems.append(
            f"expected one wheel and one sdist in {args.dist}, found {len(wheels)} and {len(sdists)}"
        )
    else:
        problems += diff(wheel_files(wheels[0]), expected_files())
        env = args.venv or Path(tempfile.mkdtemp(prefix="sy-wheel-"))
        try:
            problems += smoke(wheels[0], env)
        finally:
            if args.venv is None:
                shutil.rmtree(env, ignore_errors=True)
    for problem in problems:
        print(f"check_dist: {problem}", file=sys.stderr)
    if not problems:
        print(f"check_dist: {wheels[0].name} and {sdists[0].name} are complete and install cleanly")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
