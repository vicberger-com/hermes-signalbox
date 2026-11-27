"""H5 WP1: rename from Switchyard to Signalbox, and the upgrade path for 1.0.x users (ADR-0015)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
import warnings
from pathlib import Path
from typing import Any

import pytest

from hermes_signalbox import legacy, paths
from hermes_signalbox.core import Core
from hermes_signalbox.errors import ConfigError
from hermes_signalbox.hostlock import HostLock

ROOT = Path(__file__).resolve().parents[2]

# Places where the old name stays on purpose: history, the upgrade code and its tests, and links into old
# tags.
ALLOWED = (
    "CHANGELOG.md",
    "docs/qa/",
    "docs/adr/",
    "docs/UPGRADING-1.1.md",
    "src/hermes_signalbox/legacy.py",
    "tests/core/test_h5_rename.py",
)
_OLD_TAG_LINK = "/src/switchyard/"
# Single lines outside those places that must name the old product, because they are about upgrading from it:
# file -> text each such line contains. Anything else that says the old name fails the test.
UPGRADE_LINES = {
    "docs/QUICKSTART.md": ("For v1.0.x, use `switchyard`",),
    "docs/USER-GUIDE.md": ("| `core.migrated` | Data copied from Switchyard |",),
    "src/hermes_signalbox/core.py": ("copy a Switchyard 1.0.x data directory",),
    "src/hermes_signalbox/labels.py": ('"core.migrated": ("Data copied from Switchyard"',),
    "src/hermes_signalbox/paths.py": (
        "``SWITCHYARD_DATA_DIR``), configured",
        "SWITCHYARD_DATA_DIR still read, deprecated",
    ),
    "src/hermes_signalbox/modules/secrets/backends.py": (
        "secrets stored by Switchyard 1.0.x under its old name",
        "SWITCHYARD_SECRET_* still read, deprecated",
    ),
    "tests/test_h5_guide.py": ('assert "hermes-switchyard" not in text',),
}


_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    "htmlcov",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
}
_TEXT = {
    ".py",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
    ".js",
    ".css",
    ".cfg",
    ".ini",
    ".sh",
    ".ps1",
    "",
}


def _files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts):
            continue
        if path.is_file() and path.suffix in _TEXT:
            out.append(path)
    return out


def _tracked_hits() -> list[str]:
    """Every line outside the allow-list that still says the old name (files on disk, so it also works where
    git cannot be started from Python)."""
    hits = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(ALLOWED):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if "switchyard" not in line.lower():
                continue
            if rel == "README.md" and line.startswith("(Formerly Switchyard;"):
                continue  # the one pointer for people searching the old name
            if any(text in line for text in UPGRADE_LINES.get(rel, ())):
                continue  # an upgrade note, listed above line by line
            if _OLD_TAG_LINK in line and "/blob/v1.0.0" in line:
                continue  # links into the v1.0.0 tag, whose tree still has the old package directory
            hits.append(f"{rel}:{number}: {line.strip()[:120]}")
    return hits


def test_h5_the_old_name_survives_only_where_the_upgrade_needs_it() -> None:
    assert _tracked_hits() == []
    for rel, texts in UPGRADE_LINES.items():  # an entry nothing uses any more must be removed
        body = (ROOT / rel).read_text(encoding="utf-8")
        for text in texts:
            assert text in body, f"{rel}: stale allow-list entry {text!r}"


def test_h5_package_metadata_uses_the_new_names() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "hermes-signalbox"
    assert project["scripts"] == {"hermes-signalbox": "hermes_signalbox.cli:main"}
    assert project["entry-points"]["hermes_agent.plugins"] == {"signalbox": "hermes_signalbox.hermes"}
    plugin = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    assert "\nname: signalbox\n" in plugin
    manifest = json.loads((ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "signalbox" and manifest["tab"]["path"] == "/signalbox"


# --- environment variables ------------------------------------------------------------------------


def test_h5_old_data_dir_variable_still_works_with_a_warning(tmp_path: Path) -> None:
    old = tmp_path / "old"
    with pytest.warns(DeprecationWarning, match="SWITCHYARD_DATA_DIR is deprecated"):
        got = paths.resolve_data_dir(env={"SWITCHYARD_DATA_DIR": str(old)})
    assert got == old
    with pytest.warns(DeprecationWarning):
        assert paths.data_dir_source(env={"SWITCHYARD_DATA_DIR": str(old)}) == (
            "SWITCHYARD_DATA_DIR environment variable"
        )


def test_h5_new_data_dir_variable_wins_without_a_warning(tmp_path: Path) -> None:
    new, old = tmp_path / "new", tmp_path / "old"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        got = paths.resolve_data_dir(env={"SIGNALBOX_DATA_DIR": str(new), "SWITCHYARD_DATA_DIR": str(old)})
    assert got == new


def test_h5_old_relative_data_dir_is_still_refused() -> None:
    with pytest.warns(DeprecationWarning), pytest.raises(ConfigError, match="SWITCHYARD_DATA_DIR"):
        paths.resolve_data_dir(env={"SWITCHYARD_DATA_DIR": "relative"})


# --- data directory migration ---------------------------------------------------------------------


def _old_install(directory: Path) -> None:
    """A data directory written by the 1.0.x code path: state, audit chain, a grant."""
    with Core(data_dir=directory) as core:
        core.audit.append(
            actor="cli", action="policy.granted", module="router", detail={"capability": "ui.panel"}
        )
    (directory / "api.port").write_text("12345", encoding="utf-8")
    (directory / "api.token").write_text("old-token", encoding="utf-8")


def _digest(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.name != "host.lock"
    }


def _hermes_layout(tmp_path: Path) -> tuple[Path, Path]:
    plugin_data = tmp_path / "plugin-data"
    old = plugin_data / "agent-plugin-switchyard-3e865a8f"
    new = plugin_data / "agent-plugin-signalbox-0a1b2c3d"
    _old_install(old)
    return old, new


@pytest.fixture
def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.mark.usefixtures("_no_env")
def test_h5_hermes_data_dir_is_copied_on_first_start(tmp_path: Path) -> None:
    old, new = _hermes_layout(tmp_path)
    before = _digest(old)
    with Core(hermes_dir=new) as core:
        assert core.migration is not None and core.migration.source == old
        assert core.verify_audit().ok
        records = core.audit_log.tail(200)
        actions = [r["action"] for r in records]
        assert "core.migrated" in actions and "policy.granted" in actions  # history came along
        migrated = next(r for r in records if r["action"] == "core.migrated")
        assert migrated["detail"]["from"] == str(old)
    marker = old / legacy.MARKER  # the one file added, so that the copy is not made twice
    assert marker.is_file()
    marker.unlink()
    assert _digest(old) == before  # nothing else in the old directory changed: it still rolls back
    assert not (new / "api.token").exists() and not (new / "api.port").exists()  # runtime files stay behind
    assert not new.with_name(new.name + ".migrating").exists()


@pytest.mark.usefixtures("_no_env")
def test_h5_migration_runs_once(tmp_path: Path) -> None:
    _old, new = _hermes_layout(tmp_path)
    with Core(hermes_dir=new):
        pass
    with Core(hermes_dir=new) as core:
        assert core.migration is None
        assert [r["action"] for r in core.audit_log.tail(200)].count("core.migrated") == 1


@pytest.mark.usefixtures("_no_env")
def test_h5_old_dir_in_use_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    old, new = _hermes_layout(tmp_path)
    holder = HostLock(old / "host.lock")
    assert holder.acquire()
    try:
        with pytest.raises(ConfigError, match=r"in use by a Switchyard 1\.0\.x process"):
            Core(hermes_dir=new)
    finally:
        holder.release()
    assert not (new / "state.db").exists()
    assert not new.with_name(new.name + ".migrating").exists()


@pytest.mark.usefixtures("_no_env")
def test_h5_tampered_old_audit_is_refused(tmp_path: Path) -> None:
    old, new = _hermes_layout(tmp_path)
    log = sorted((old / "audit").glob("*.jsonl"))[0]
    lines = log.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["actor"] = "someone-else"
    log.write_text("\n".join([json.dumps(record), *lines[1:]]) + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="does not verify"):
        Core(hermes_dir=new)
    assert not (new / "state.db").exists()
    assert not new.with_name(new.name + ".migrating").exists()


@pytest.mark.usefixtures("_no_env")
def test_h5_several_old_dirs_are_refused(tmp_path: Path) -> None:
    old, new = _hermes_layout(tmp_path)
    _old_install(old.with_name("agent-plugin-switchyard-ffffffff"))
    with pytest.raises(ConfigError, match="several Switchyard data directories"):
        Core(hermes_dir=new)


def test_h5_named_directories_never_migrate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _old, new = _hermes_layout(tmp_path)
    with Core(data_dir=new) as core:  # an explicit directory is used as is
        assert core.migration is None
    other = tmp_path / "plugin-data" / "agent-plugin-signalbox-99999999"
    monkeypatch.setenv("SIGNALBOX_DATA_DIR", str(tmp_path / "elsewhere"))
    with Core(hermes_dir=other) as core:
        assert core.migration is None and core.data_dir == tmp_path / "elsewhere"


@pytest.mark.usefixtures("_no_env")
def test_h5_platform_default_dir_is_copied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "share"
    _old_install(base / "switchyard")
    monkeypatch.setattr(paths, "default_data_dir", lambda **_: base / "signalbox")
    with Core() as core:
        assert core.migration is not None and core.data_dir == base / "signalbox"


@pytest.mark.usefixtures("_no_env")
def test_h5_empty_new_dir_created_by_the_host_is_replaced(tmp_path: Path) -> None:
    old, new = _hermes_layout(tmp_path)
    new.mkdir()
    assert legacy.migrate_data_dir(new, [old]) is not None
    assert (new / "state.db").is_file()


def test_h5_non_empty_new_dir_is_refused(tmp_path: Path) -> None:
    old, new = _hermes_layout(tmp_path)
    new.mkdir()
    (new / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="is not empty"):
        legacy.migrate_data_dir(new, [old])
    assert (new / "stray.txt").exists() and not (new / "state.db").exists()


# --- stored secrets -------------------------------------------------------------------------------


def _backends() -> Any:
    import importlib.util

    path = ROOT / "src" / "hermes_signalbox" / "modules" / "secrets" / "backends.py"
    spec = importlib.util.spec_from_file_location("h5_backends", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _backends()


def test_h5_env_backend_reads_the_old_prefix_with_a_warning() -> None:
    env = B.EnvBackend({"SWITCHYARD_SECRET_API_KEY": "old"})
    with pytest.warns(DeprecationWarning, match="SWITCHYARD_SECRET_API_KEY"):
        assert env.get("api.key") == "old"
    both = B.EnvBackend({"SWITCHYARD_SECRET_API_KEY": "old", "SIGNALBOX_SECRET_API_KEY": "new"})
    assert both.get("api.key") == "new"
    with pytest.raises(KeyError):
        B.EnvBackend({}).get("api.key")


class _Done:
    def __init__(self, code: int, out: str = "", err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = code, out, err


class _Run:
    def __init__(self, *results: _Done) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_: Any) -> _Done:
        self.calls.append(argv)
        return self.results.pop(0)


def test_h5_keychain_falls_back_to_the_old_service_for_reads() -> None:
    run = _Run(_Done(44), _Done(0, "legacy-value\n"))
    assert B.KeychainBackend(run).get("api.key") == "legacy-value"
    assert [c[3] for c in run.calls] == ["signalbox", "switchyard"]


def test_h5_keychain_locked_new_service_does_not_fall_back() -> None:
    run = _Run(_Done(51))
    with pytest.raises(B.SecretLocked):
        B.KeychainBackend(run).get("api.key")
    assert len(run.calls) == 1  # fail closed: a locked keychain is not "missing"


def test_h5_secret_tool_falls_back_and_writes_only_the_new_service() -> None:
    run = _Run(_Done(1), _Done(0, "legacy-value"), _Done(0))
    s = B.SecretToolBackend(run)
    assert s.get("api.key") == "legacy-value"
    s.set("api.key", "x")
    assert run.calls[1][3] == "switchyard" and "signalbox" in run.calls[2]


def test_h5_wincred_falls_back_for_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    store = {"switchyard:api.key": "legacy-value"}

    class Fake:
        def read(self, target: str) -> str:
            return store[target]

    monkeypatch.setattr(B, "_wincred", Fake)
    assert B.WinCredBackend().get("api.key") == "legacy-value"
    store["signalbox:api.key"] = "new-value"
    assert B.WinCredBackend().get("api.key") == "new-value"


def test_h5_cli_is_hermes_signalbox() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "hermes_signalbox.cli", "--help"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0 and done.stdout.startswith("usage: hermes-signalbox")
