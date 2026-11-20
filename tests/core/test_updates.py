"""Update control: pinned sources, verify, stage, swap, health check, roll back (spec section 3)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sy_testing import GOOD, write_module

from switchyard.core import Core
from switchyard.errors import UpdateError
from switchyard.updates import GitFetcher, git_usable

URL = "https://example.invalid/vendor/ext.git"
OLD = "1" * 40
NEW = "2" * 40
BAD = "3" * 40


class FakeFetcher:
    """Maps (url, ref) to a prepared directory; records calls."""

    def __init__(self) -> None:
        self.sources: dict[tuple[str, str], Path] = {}
        self.calls: list[tuple[str, str]] = []

    def fetch(self, url: str, ref: str, dest: Path) -> None:
        self.calls.append((url, ref))
        src = self.sources.get((url, ref))
        if src is None:
            raise UpdateError(f"no such commit {ref}")
        shutil.copytree(src, dest, symlinks=True)


def _git_manifest(d: Path, *, version: str, url: str = URL) -> None:
    toml = d / "module.toml"
    text = toml.read_text(encoding="utf-8").replace('version = "0.1.0"', f'version = "{version}"')
    text += f'[update]\nsource = "git"\nurl = "{url}"\nref = "{OLD}"\n'
    toml.write_text(text, encoding="utf-8")


def _source(
    root: Path, name: str, *, version: str, code: str = GOOD, url: str = URL, module_id: str = "ext"
) -> Path:
    d = write_module(root / name, module_id, code, isolation="subprocess")
    _git_manifest(d, version=version, url=url)
    return d


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Any:
    data = tmp_path / "data"
    installed = _source(tmp_path / "v1", "x", version="0.1.0")
    (data / "modules").mkdir(parents=True)
    shutil.copytree(installed, data / "modules" / "ext")
    fetcher = FakeFetcher()
    fetcher.sources[(URL, NEW)] = _source(tmp_path / "v2", "x", version="0.2.0")
    unhealthy = GOOD.replace('return (self.ctx is not None, "ok")', 'return (False, "broken")')
    fetcher.sources[(URL, BAD)] = _source(tmp_path / "v3", "x", version="0.3.0", code=unhealthy)
    core = Core(data_dir=data, fetcher=fetcher)
    yield core, fetcher, tmp_path
    core.close()


def _version(core: Core) -> str:
    return str(core.run("module", "show", {"id": "ext"}, actor="t")["version"])


def test_update_swaps_and_keeps_the_module_running(env: Any) -> None:
    core, fetcher, _ = env
    core.run("module", "activate", {"id": "ext"}, actor="t")
    result = core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    assert result == {"id": "ext", "from": "0.1.0", "to": "0.2.0", "ref": NEW, "rolled_back": False}
    assert _version(core) == "0.2.0" and fetcher.calls == [(URL, NEW)]
    assert core.run("module", "health", {"id": "ext"}, actor="t")["ok"] is True
    actions = [r["action"] for r in core.run("audit", "tail", {"n": 30}, actor="t")]
    assert "module.updated" in actions
    assert not list((core.data_dir / "staging" / "ext").glob("stage-*"))


def test_unhealthy_update_rolls_back(env: Any) -> None:
    core, _, _ = env
    core.run("module", "activate", {"id": "ext"}, actor="t")
    result = core.run("module", "update", {"id": "ext", "ref": BAD}, actor="t")
    assert result["rolled_back"] is True and result["to"] == "0.1.0"
    assert _version(core) == "0.1.0"
    assert core.run("module", "health", {"id": "ext"}, actor="t") == {"ok": True, "detail": "ok"}
    actions = [r["action"] for r in core.run("audit", "tail", {"n": 30}, actor="t")]
    assert "module.rolled_back" in actions


def test_update_that_fails_to_activate_rolls_back(env: Any) -> None:
    core, fetcher, tmp_path = env
    crash = "5" * 40
    code = GOOD.replace('ctx.log("{id}", "activated")', 'raise RuntimeError("new version is broken")')
    fetcher.sources[(URL, crash)] = _source(tmp_path / "v7", "x", version="0.7.0", code=code)
    core.run("module", "activate", {"id": "ext"}, actor="t")
    result = core.run("module", "update", {"id": "ext", "ref": crash}, actor="t")
    assert result["rolled_back"] is True and _version(core) == "0.1.0"
    assert core.run("module", "show", {"id": "ext"}, actor="t")["status"] == "active"


def test_inactive_module_updates_without_starting(env: Any) -> None:
    core, _, _ = env
    core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    assert core.run("module", "show", {"id": "ext"}, actor="t")["status"] == "verified"


def test_manual_rollback_restores_the_previous_version(env: Any) -> None:
    core, _, _ = env
    core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    assert core.run("module", "rollback", {"id": "ext"}, actor="t") == {"id": "ext", "version": "0.1.0"}
    assert _version(core) == "0.1.0"
    with pytest.raises(UpdateError, match="no previous version"):
        core.run("module", "rollback", {"id": "ext"}, actor="t")


@pytest.mark.parametrize("ref", ["main", "abc123", "G" * 40, "A" * 40])
def test_ref_must_be_a_full_commit_sha(env: Any, ref: str) -> None:
    core, fetcher, _ = env
    with pytest.raises(UpdateError, match="commit SHA"):
        core.run("module", "update", {"id": "ext", "ref": ref}, actor="t")
    assert fetcher.calls == []


def test_staged_manifest_cannot_change_id_or_source(env: Any) -> None:
    core, fetcher, tmp_path = env
    other_id = "9" * 40
    fetcher.sources[(URL, other_id)] = _source(tmp_path / "v4", "x", version="0.4.0", module_id="other")
    with pytest.raises(UpdateError, match="module id"):
        core.run("module", "update", {"id": "ext", "ref": other_id}, actor="t")
    redirect = "8" * 40
    fetcher.sources[(URL, redirect)] = _source(
        tmp_path / "v5", "x", version="0.5.0", url="https://evil.invalid/x.git"
    )
    with pytest.raises(UpdateError, match="source"):
        core.run("module", "update", {"id": "ext", "ref": redirect}, actor="t")
    broken = "7" * 40
    src = _source(tmp_path / "v6", "x", version="0.6.0")
    (src / "module.toml").write_text("schema = 2", encoding="utf-8")
    fetcher.sources[(URL, broken)] = src
    with pytest.raises(UpdateError, match="manifest"):
        core.run("module", "update", {"id": "ext", "ref": broken}, actor="t")
    assert _version(core) == "0.1.0"
    assert not list((core.data_dir / "staging" / "ext").glob("stage-*"))


def test_fetch_failure_changes_nothing(env: Any) -> None:
    core, _, _ = env
    with pytest.raises(UpdateError, match="no such commit"):
        core.run("module", "update", {"id": "ext", "ref": "4" * 40}, actor="t")
    assert _version(core) == "0.1.0"


def test_bundled_modules_are_not_updated_here(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_module(data / "modules", "plain", isolation="subprocess")
    with Core(data_dir=data, fetcher=FakeFetcher()) as core, pytest.raises(UpdateError, match="bundled"):
        core.run("module", "update", {"id": "plain", "ref": NEW}, actor="t")


def test_update_needs_the_hosting_process(env: Any) -> None:
    core, _, _ = env
    with (
        Core(data_dir=core.data_dir, hosting=False) as client,
        pytest.raises(Exception, match="does not host"),
    ):
        client.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")


# real git -------------------------------------------------------------------------------------------------

needs_git = pytest.mark.skipif(not git_usable(), reason="no git executable this process may run")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603, S607


@needs_git
def test_git_fetcher_checks_out_the_exact_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("one", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("two", encoding="utf-8")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "two")
    fetcher = GitFetcher(allow_file_protocol=True)
    dest = tmp_path / "out"
    fetcher.fetch(repo.as_uri(), first, dest)
    assert (dest / "a.txt").read_text(encoding="utf-8") == "one" and not (dest / ".git").exists()
    with pytest.raises(UpdateError):
        fetcher.fetch(repo.as_uri(), "f" * 40, tmp_path / "missing")


@needs_git
def test_git_fetcher_refuses_file_urls_by_default(tmp_path: Path) -> None:
    with pytest.raises(UpdateError, match="https"):
        GitFetcher().fetch((tmp_path / "x").as_uri(), "a" * 40, tmp_path / "out")


def test_git_fetcher_rejects_bad_input_without_running_git(tmp_path: Path) -> None:
    fetcher = GitFetcher(git="definitely-not-git")
    with pytest.raises(UpdateError, match="https"):
        fetcher.fetch("http://example.invalid/x.git", "a" * 40, tmp_path / "o")
    with pytest.raises(UpdateError, match="commit SHA"):
        fetcher.fetch("https://example.invalid/x.git", "main", tmp_path / "o")
    with pytest.raises(UpdateError, match="git"):
        fetcher.fetch("https://example.invalid/x.git", "a" * 40, tmp_path / "o")


def test_staged_tree_with_symlinks_is_rejected(env: Any) -> None:
    core, fetcher, tmp_path = env
    src = _source(tmp_path / "v8", "x", version="0.8.0")
    try:
        (src / "escape.py").symlink_to(tmp_path / "outside.py")
    except OSError:
        pytest.skip("this account cannot create symlinks")
    link = "6" * 40
    fetcher.sources[(URL, link)] = src
    with pytest.raises(UpdateError, match="symlink"):
        core.run("module", "update", {"id": "ext", "ref": link}, actor="t")
    assert _version(core) == "0.1.0"
