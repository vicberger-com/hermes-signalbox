"""Update control: pinned sources, verify, stage, swap, health check, roll back (spec section 3)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sy_testing import GOOD, write_module

from hermes_signalbox.core import Core
from hermes_signalbox.errors import ChannelNotFound, UpdateError
from hermes_signalbox.updates import GitFetcher, git_usable

URL = "https://example.invalid/vendor/ext.git"
OLD = "1" * 40
NEW = "2" * 40
BAD = "3" * 40


class FakeFetcher:
    """Maps (url, ref) to a prepared directory; records calls."""

    def __init__(self) -> None:
        self.sources: dict[tuple[str, str], Path] = {}
        self.calls: list[tuple[str, str]] = []
        self.heads: dict[tuple[str, str], str] = {}

    def latest(self, url: str, channel: str) -> str:
        if (url, channel) not in self.heads:
            raise ChannelNotFound(f"channel {channel!r} not found")
        return self.heads[(url, channel)]

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
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)


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
    assert {k: result[k] for k in ("id", "from", "to", "ref", "rolled_back")} == {
        "id": "ext", "from": "0.1.0", "to": "0.2.0", "ref": NEW, "rolled_back": False}  # fmt: skip
    assert result["delta"]["files"]["changed"] == ["module.toml"]  # SBOM delta for every update
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
    health = core.run("module", "health", {"id": "ext"}, actor="t")
    assert (health["ok"], health["detail"]) == (True, "ok")
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
    result = core.run("module", "rollback", {"id": "ext"}, actor="t")
    assert {k: result[k] for k in ("id", "version", "ok")} == {"id": "ext", "version": "0.1.0", "ok": True}
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
    from hermes_signalbox.updates import resolved_git

    exe = resolved_git() or "git"  # the same git the fetcher uses (H1 D-2)
    return subprocess.run([exe, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603


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


# M12 (ADR-0011): preview, SBOM delta, patch notes, digest pinning, widening, channels ---------------------

WIDE = "4" * 40


def _with_changelog(d: Path, version: str) -> None:
    (d / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [{version}] - 2026-11-20\n\n- Faster.\x1b[31m red\n\n## [0.1.0]\n\n- Old.\n",
        encoding="utf-8",
    )


def test_preview_reports_delta_and_notes_without_applying(env: Any) -> None:
    core, fetcher, _ = env
    _with_changelog(fetcher.sources[(URL, NEW)], "0.2.0")
    out = core.run("module", "preview", {"id": "ext", "ref": NEW}, actor="t")
    assert _version(core) == "0.1.0"  # nothing applied
    assert out["delta"]["files"]["added"] == ["CHANGELOG.md"]
    assert out["delta"]["declared"]["version"] == {"from": "0.1.0", "to": "0.2.0"}
    assert out["notes"].startswith("## [0.2.0]") and "Old." not in out["notes"] and "\x1b" not in out["notes"]
    assert not list((core.data_dir / "staging" / "ext").glob("stage-*"))
    result = core.run(
        "module", "update", {"id": "ext", "ref": NEW, "digest": out["delta"]["digest"]}, actor="t"
    )
    assert result["to"] == "0.2.0" and result["notes"] == out["notes"]
    sbom = core.data_dir / "staging" / "ext" / f"sbom-{NEW}.json"
    assert json.loads(sbom.read_text(encoding="utf-8"))["digest"] == out["delta"]["digest"]


def test_tampered_update_rejected(env: Any) -> None:
    """The files fetched at update time differ from the ones reviewed in preview: refused, nothing applied."""
    core, fetcher, _ = env
    digest = core.run("module", "preview", {"id": "ext", "ref": NEW}, actor="t")["delta"]["digest"]
    entry = fetcher.sources[(URL, NEW)] / "mod.py"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# injected\n", encoding="utf-8")
    with pytest.raises(UpdateError, match="previewed digest"):
        core.run("module", "update", {"id": "ext", "ref": NEW, "digest": digest}, actor="t")
    assert _version(core) == "0.1.0"
    rejected = [
        r for r in core.run("audit", "tail", {"n": 20}, actor="t") if r["action"] == "module.update_rejected"
    ]
    assert rejected and "digest" in rejected[-1]["detail"]["reason"]


def test_failed_health_check_rolls_back_with_delta(env: Any) -> None:
    core, _, _ = env
    core.run("module", "activate", {"id": "ext"}, actor="t")
    result = core.run("module", "update", {"id": "ext", "ref": BAD}, actor="t")
    assert result["rolled_back"] and _version(core) == "0.1.0"
    assert result["delta"]["declared"]["version"]["to"] == "0.3.0"


def test_widening_needs_explicit_acceptance(env: Any) -> None:
    core, fetcher, tmp = env
    wide = _source(tmp / "v4", "x", version="0.4.0")
    toml = wide / "module.toml"
    text = toml.read_text(encoding="utf-8")
    text = text.replace("[capabilities]\n", '[capabilities]\nnet_hosts = ["api.example.com"]\n', 1)
    text = re.sub(
        r"request = \[([^\]]*)\]",
        lambda m: (
            f'request = [{m.group(1)}, "net.outbound"]'
            if m.group(1).strip()
            else 'request = ["net.outbound"]'
        ),
        text,
        count=1,
    )
    toml.write_text(text, encoding="utf-8")
    fetcher.sources[(URL, WIDE)] = wide
    preview = core.run("module", "preview", {"id": "ext", "ref": WIDE}, actor="t")
    assert any(w.startswith("net_hosts") for w in preview["delta"]["widens"])
    assert any("net.outbound" in w for w in preview["delta"]["widens"])
    with pytest.raises(UpdateError, match="widens"):
        core.run("module", "update", {"id": "ext", "ref": WIDE}, actor="t")
    assert _version(core) == "0.1.0"
    result = core.run("module", "update", {"id": "ext", "ref": WIDE, "accept_wider": True}, actor="t")
    assert result["to"] == "0.4.0"


def test_channel_checks(env: Any) -> None:
    core, fetcher, _ = env
    out = core.run("module", "check_updates", {}, actor="t")["modules"]
    assert out == [{"id": "ext", "channel": "main", "error": "channel not found"}]
    fetcher.heads[(URL, "main")] = NEW
    (row,) = core.run("module", "check_updates", {}, actor="t")["modules"]
    assert row == {"id": "ext", "channel": "main", "installed": OLD, "available": NEW, "update": True}
    core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    (row,) = core.run("module", "check_updates", {}, actor="t")["modules"]
    assert row["installed"] == NEW and not row["update"]
    core.run("module", "rollback", {"id": "ext"}, actor="t")
    (row,) = core.run("module", "check_updates", {}, actor="t")["modules"]
    assert row["installed"] == OLD


@needs_git
def test_git_latest_reads_channel_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "stable")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
    head = _git(repo, "rev-parse", "HEAD")
    fetcher = GitFetcher(allow_file_protocol=True)
    assert fetcher.latest(repo.as_uri(), "stable") == head
    for bad in ("../x", "-x", "a b"):
        with pytest.raises(UpdateError):
            fetcher.latest(repo.as_uri(), bad)
    with pytest.raises(UpdateError, match="not found"):
        fetcher.latest(repo.as_uri(), "nope")
    with pytest.raises(UpdateError, match="https"):
        GitFetcher().latest("http://example.invalid/x.git", "main")


# M12 review regressions -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["__pycache__/mod.cpython-311.pyc", "evil.pth", "x.pyc"])
def test_compiled_or_path_files_refused(env: Any, name: str) -> None:
    core, fetcher, _ = env
    target = fetcher.sources[(URL, NEW)] / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"payload")
    with pytest.raises(UpdateError, match="compiled or path files"):
        core.run("module", "preview", {"id": "ext", "ref": NEW}, actor="t")
    target.unlink()


def test_new_contributions_widen(env: Any) -> None:
    core, fetcher, _ = env
    toml = fetcher.sources[(URL, NEW)] / "module.toml"
    text = toml.read_text(encoding="utf-8")
    text = re.sub(r"log_streams = \[", 'log_streams = ["extra", ', text, count=1)
    assert '"extra"' in text
    toml.write_text(text, encoding="utf-8")
    delta = core.run("module", "preview", {"id": "ext", "ref": NEW}, actor="t")["delta"]
    assert "contributes.log_streams: extra" in delta["widens"]


def test_patch_notes_exact_version_and_format_chars(tmp_path: Path) -> None:
    from hermes_signalbox.updates import patch_notes

    (tmp_path / "CHANGELOG.md").write_text(
        "## 1.20.0\n- wrong\n## 1.2 - date\n- right\u202egnp.exe\n## 1.1\n", encoding="utf-8"
    )
    assert patch_notes(tmp_path, "1.2") == "## 1.2 - date\n- rightgnp.exe"


def test_checks_are_single_and_cached(env: Any) -> None:
    core, fetcher, _ = env
    fetcher.heads[(URL, "main")] = NEW
    view_rows = core.updates.cached_checks(max_age_s=0)
    assert view_rows[0]["update"]
    fetcher.heads[(URL, "main")] = OLD
    assert core.updates.cached_checks(max_age_s=0)[0]["update"]  # within the minimum interval: cached
    core.updates._checking.acquire()
    try:
        assert core.updates.check_all()[0]["available"] == NEW  # busy: last result, no second check
    finally:
        core.updates._checking.release()


def test_rollback_restores_ref_and_prunes(env: Any) -> None:
    core, fetcher, tmp = env
    refs = []
    for n in range(5):
        ref = f"{n + 5}" * 40
        fetcher.sources[(URL, ref)] = _source(tmp / f"r{n}", "x", version=f"0.{n + 5}.0")
        core.run("module", "update", {"id": "ext", "ref": ref}, actor="t")
        refs.append(ref)
    previous = list((core.data_dir / "staging" / "ext").glob("previous-*"))
    assert len([p for p in previous if p.is_dir()]) == 3
    core.run("module", "rollback", {"id": "ext"}, actor="t")
    assert _version(core) == "0.8.0" and core.updates.installed_ref("ext") == refs[-2]


# H1 WP7: failure paths --------------------------------------------------------------------------------


def test_h1_b1_failed_swap_puts_the_live_module_back(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    core, _, _ = env
    core.run("module", "activate", {"id": "ext"}, actor="t")
    real = Path.rename
    calls: list[str] = []

    def flaky(self: Path, target: Any) -> Any:
        calls.append(self.name)
        if self.name.startswith(
            "stage-"
        ):  # the second rename: stage -> live (a directory held open on Windows)
            raise PermissionError(13, "simulated: directory in use")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    with pytest.raises(UpdateError, match="PermissionError"):
        core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    monkeypatch.setattr(Path, "rename", real)
    assert (core.data_dir / "modules" / "ext" / "module.toml").is_file()
    assert _version(core) == "0.1.0"
    assert core.run("module", "show", {"id": "ext"}, actor="t")["status"] == "active"
    actions = [r["action"] for r in core.run("audit", "tail", {"n": 30}, actor="t")]
    assert "module.rolled_back" in actions


def test_h1_b1_activation_error_after_swap_rolls_back(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    core, _, _ = env
    core.run("module", "activate", {"id": "ext"}, actor="t")
    real = core.manager.activate
    state = {"n": 0}

    def boom(module_id: str, *, actor: str) -> None:
        state["n"] += 1
        if state["n"] == 1:  # the restart of the new version
            raise RuntimeError("simulated post-swap failure")
        real(module_id, actor=actor)

    monkeypatch.setattr(core.manager, "activate", boom)
    result = core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    assert result["rolled_back"] is True and _version(core) == "0.1.0"
    assert core.updates.installed_ref("ext") == OLD
    assert core.run("module", "show", {"id": "ext"}, actor="t")["status"] == "active"


def test_h1_b2_git_work_does_not_hold_the_core_lock(env: Any) -> None:
    import threading
    import time

    core, fetcher, _ = env
    release = threading.Event()
    fetcher.heads[(URL, "main")] = NEW
    slow_latest = fetcher.latest

    def slow(url: str, channel: str) -> str:
        release.wait(10)
        return slow_latest(url, channel)

    fetcher.latest = slow  # type: ignore[method-assign]
    worker = threading.Thread(target=core.run, args=("module", "check_updates", {}), kwargs={"actor": "t"})
    worker.start()
    time.sleep(0.2)
    start = time.monotonic()
    core.run("module", "list", {}, actor="t")
    waited = time.monotonic() - start
    release.set()
    worker.join(10)
    assert waited < 0.5, waited


def test_h1_cr1_module_changed_during_fetch_is_not_swapped(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses

    core, fetcher, _ = env
    manager = core.updates._manager
    real_manifest = manager.manifest
    fetched = {"done": False}
    real_fetch = fetcher.fetch

    def fetch(url: str, ref: str, dest: Path) -> None:
        real_fetch(url, ref, dest)
        fetched["done"] = True  # the operator replaced the module while git ran (no core lock held)

    def manifest(module_id: str) -> Any:
        m = real_manifest(module_id)
        return dataclasses.replace(m, version="9.9.9") if fetched["done"] else m

    monkeypatch.setattr(fetcher, "fetch", fetch)
    monkeypatch.setattr(manager, "manifest", manifest)
    with pytest.raises(UpdateError, match="changed while"):
        core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    monkeypatch.setattr(manager, "manifest", real_manifest)
    assert _version(core) == "0.1.0"
    actions = [r["action"] for r in core.run("audit", "tail", {"n": 10}, actor="t")]
    assert "module.update_rejected" in actions and "module.updated" not in actions


@pytest.mark.parametrize("name", ["evil.pyd", "evil.so", "libx.dylib", "x.dll", "run.pyw", "X.PYC", "E.PTH"])
def test_h1_b11_binary_and_case_variant_files_refused(env: Any, name: str) -> None:
    core, fetcher, _ = env
    target = fetcher.sources[(URL, NEW)] / name
    target.write_bytes(b"payload")
    try:
        with pytest.raises(UpdateError, match="compiled"):
            core.run("module", "preview", {"id": "ext", "ref": NEW}, actor="t")
    finally:
        target.unlink()


# 1.1 backlog batch 5: update and rollback integrity (H1 B-12 #104, B-13 #105) -------------------------------


def _audited(core: Core, action: str) -> list[dict[str, Any]]:
    return [r for r in core.run("audit", "tail", {"n": 20}, actor="t") if r["action"] == action]


def test_h1_b12_an_older_version_needs_allow_downgrade(env: Any) -> None:
    core, fetcher, tmp = env
    core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")  # now 0.2.0
    older = "6" * 40
    fetcher.sources[(URL, older)] = _source(tmp / "v15", "x", version="0.1.5")
    preview = core.run("module", "preview", {"id": "ext", "ref": older}, actor="t")
    assert preview["downgrade"] is True
    with pytest.raises(UpdateError, match="older"):
        core.run("module", "update", {"id": "ext", "ref": older}, actor="t")
    assert _version(core) == "0.2.0"
    core.run("module", "update", {"id": "ext", "ref": older, "allow_downgrade": True}, actor="t")
    assert _version(core) == "0.1.5"


def test_h1_b12_prerelease_is_older_and_same_version_is_not(env: Any) -> None:
    core, fetcher, tmp = env
    core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")  # 0.2.0
    rc, same = "7" * 40, "8" * 40
    fetcher.sources[(URL, rc)] = _source(tmp / "rc", "x", version="0.2.0-rc1")
    fetcher.sources[(URL, same)] = _source(tmp / "same", "x", version="0.2.0+build5")
    assert core.run("module", "preview", {"id": "ext", "ref": rc}, actor="t")["downgrade"] is True
    assert core.run("module", "preview", {"id": "ext", "ref": same}, actor="t")["downgrade"] is False
    core.run("module", "update", {"id": "ext", "ref": same}, actor="t")


def test_h1_b13_rollback_runs_the_health_check_and_reports_it(env: Any) -> None:
    core, _, _ = env
    core.run("module", "update", {"id": "ext", "ref": BAD}, actor="t")  # inactive: installs unhealthy 0.3.0
    core.run("module", "update", {"id": "ext", "ref": NEW, "allow_downgrade": True}, actor="t")
    core.run("module", "activate", {"id": "ext"}, actor="t")
    result = core.run("module", "rollback", {"id": "ext"}, actor="t")
    assert result["version"] == "0.3.0" and result["ok"] is False and "health" in result["detail"]
    record = _audited(core, "module.rolled_back")
    assert record[-1]["detail"]["health"] == "failed"


def test_h1_b13_healthy_rollback_is_ok(env: Any) -> None:
    core, _, _ = env
    core.run("module", "activate", {"id": "ext"}, actor="t")
    core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    result = core.run("module", "rollback", {"id": "ext"}, actor="t")
    assert result["ok"] is True and result["version"] == "0.1.0"
    record = _audited(core, "module.rolled_back")
    assert record[-1]["detail"]["health"] == "ok" and record[-1]["detail"]["digest"] == "verified"


def test_h1_b13_a_previous_version_changed_on_disk_is_refused(env: Any) -> None:
    core, _, _ = env
    core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    (previous,) = [p for p in (core.data_dir / "staging" / "ext").glob("previous-*") if p.is_dir()]
    (previous / "module.py").write_text("# changed after it was set aside\n", encoding="utf-8")
    with pytest.raises(UpdateError, match="changed"):
        core.run("module", "rollback", {"id": "ext"}, actor="t")
    assert _version(core) == "0.2.0"


def test_h1_b13_previous_version_without_a_recorded_digest_still_rolls_back(env: Any) -> None:
    core, _, _ = env
    core.run("module", "update", {"id": "ext", "ref": NEW}, actor="t")
    for sidecar in (core.data_dir / "staging" / "ext").glob("previous-*.digest"):
        sidecar.unlink()  # set aside by 1.0.x, which recorded no digest
    assert core.run("module", "rollback", {"id": "ext"}, actor="t")["version"] == "0.1.0"
    record = _audited(core, "module.rolled_back")
    assert record[-1]["detail"]["digest"] == "unrecorded"
