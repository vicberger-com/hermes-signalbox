"""Update control for modules installed from a pinned git source (spec section 3, Update control).

Only modules under ``<data_dir>/modules`` with ``[update] source = "git"`` are updated here; bundled modules
update with the Switchyard release. ``UpdateController.update(id, ref)``:

1. ``ref`` must be a full lower-case commit SHA; the URL is the one pinned in the *installed* manifest.
2. Fetch exactly that commit into ``<data_dir>/staging/<id>/stage-<ref>``. ``GitFetcher`` runs ``git`` with a
   fixed argument list, a scrubbed environment, no hooks, https only, a timeout, and checks ``HEAD == ref``
   before removing ``.git``.
3. Verify the staged manifest: valid, same module id, same pinned source URL (an update cannot redirect where
   future updates come from).
4. Deactivate if running, swap directories by rename (previous version kept as ``previous-<version>-<time>``),
   reload, reactivate if it was running, run the health check.
5. Any failure in step 4 restores the previous directory and state (``module.rolled_back``). Every outcome is
   audited. ``rollback(id)`` restores the most recent previous version on request.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from switchyard.capabilities import CORE_ACTOR, AuditSink
from switchyard.errors import ManifestError, UpdateError
from switchyard.lifecycle import ModuleManager, ModuleStatus
from switchyard.manifest import load_manifest

_SHA = re.compile(r"[0-9a-f]{40}\Z")
GIT_TIMEOUT_S = 300
_GIT_ENV_ALLOW = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")


class Fetcher(Protocol):
    def fetch(self, url: str, ref: str, dest: Path) -> None: ...


def _check_ref(ref: str) -> None:
    if not isinstance(ref, str) or not _SHA.match(ref):
        raise UpdateError("ref must be a full 40-character lower-case commit SHA")


def git_usable(git: str = "git") -> bool:
    """True if this process can run ``git`` (some sandboxed installs cannot)."""
    exe = shutil.which(git)
    if exe is None:
        return False
    try:
        subprocess.run([exe, "--version"], capture_output=True, timeout=30, check=True)  # noqa: S603 # nosec B603
    except (OSError, subprocess.SubprocessError):
        return False
    return True


class GitFetcher:
    """Fetch one exact commit with the system ``git``. Used only by the core (T0)."""

    def __init__(self, *, git: str = "git", allow_file_protocol: bool = False) -> None:
        self._git = git
        self._allow_file = allow_file_protocol

    def _run(self, args: list[str], cwd: Path) -> str:
        exe = shutil.which(self._git)
        if exe is None:
            raise UpdateError("git executable not found")
        env = {k: v for k in _GIT_ENV_ALLOW if (v := os.environ.get(k)) is not None}
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        protocol = "always" if self._allow_file else "never"
        cmd = [exe, "-c", f"protocol.file.allow={protocol}", "-c", "core.hooksPath=" + os.devnull, *args]
        try:
            # Fixed argv; url and ref are validated above; no shell.
            done = subprocess.run(  # noqa: S603 # nosec B603
                cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f"git could not run: {type(exc).__name__}") from None
        if done.returncode != 0:
            raise UpdateError(f"git {args[0]} failed (exit {done.returncode})")
        return done.stdout.strip()

    def fetch(self, url: str, ref: str, dest: Path) -> None:
        if not (url.startswith("https://") or (self._allow_file and url.startswith("file:"))):
            raise UpdateError("update URLs must use https://")
        _check_ref(ref)
        dest.mkdir(parents=True)
        try:
            self._run(["init", "-q"], dest)
            self._run(["fetch", "-q", "--depth", "1", "--no-tags", url, ref], dest)
            self._run(["checkout", "-q", "--detach", "FETCH_HEAD"], dest)
            head = self._run(["rev-parse", "HEAD"], dest)
        except UpdateError:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        if head != ref:
            shutil.rmtree(dest, ignore_errors=True)
            raise UpdateError(f"fetched commit {head} does not match the requested {ref}")
        shutil.rmtree(dest / ".git", onerror=_force_remove)


def _force_remove(
    func: Any, path: str, _exc: Any
) -> None:  # pragma: no cover - read-only git objects on Windows
    os.chmod(path, 0o700)
    func(path)


@dataclass(frozen=True)
class UpdateResult:
    id: str
    from_version: str
    to_version: str
    ref: str
    rolled_back: bool

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "from": self.from_version, "to": self.to_version, "ref": self.ref,
                "rolled_back": self.rolled_back}  # fmt: skip


class UpdateController:
    def __init__(self, manager: ModuleManager, audit: AuditSink, data_dir: Path, fetcher: Fetcher) -> None:
        self._manager = manager
        self._audit = audit
        self._modules_dir = (data_dir / "modules").resolve()
        self._staging = data_dir / "staging"
        self._fetcher = fetcher

    def _record(self, action: str, module_id: str, actor: str, **detail: str) -> None:
        self._audit.append(actor=actor, action=action, module=module_id, detail=detail)

    def _installed(self, module_id: str) -> Path:
        manifest = self._manager.manifest(module_id)
        if manifest.update_source != "git" or not manifest.update_url:
            raise UpdateError(f"module {module_id!r} is bundled; it updates with the Switchyard release")
        directory = manifest.directory.resolve()
        if directory.parent != self._modules_dir:
            raise UpdateError(f"module {module_id!r} is not installed under {self._modules_dir}")
        return directory

    def update(self, module_id: str, ref: str, *, actor: str) -> UpdateResult:
        _check_ref(ref)
        current = self._installed(module_id)
        old = self._manager.manifest(module_id)
        stage_root = self._staging / module_id
        stage_root.mkdir(parents=True, exist_ok=True)
        stage = stage_root / f"stage-{ref}"
        shutil.rmtree(stage, ignore_errors=True)
        try:
            self._fetcher.fetch(old.update_url or "", ref, stage)
            try:
                new = load_manifest(stage)
            except ManifestError as exc:
                raise UpdateError(f"staged manifest is invalid: {'; '.join(exc.errors)[:300]}") from None
            if new.id != module_id:
                raise UpdateError(f"staged module id {new.id!r} does not match {module_id!r}")
            if new.update_source != "git" or new.update_url != old.update_url:
                raise UpdateError("staged manifest changes the pinned update source; refused")
        except UpdateError as exc:
            shutil.rmtree(stage, ignore_errors=True)
            self._record("module.update_rejected", module_id, actor, ref=ref, reason=str(exc)[:300])
            raise

        was_active = self._manager.info(module_id).status is ModuleStatus.ACTIVE
        previous = (
            stage_root / f"previous-{old.version}-{time.strftime('%Y%m%dT%H%M%S')}-{time.monotonic_ns()}"
        )
        self._manager.deactivate(module_id, actor=actor, reason="update")
        current.rename(previous)
        stage.rename(current)
        if self._restart(module_id, was_active):
            self._record(
                "module.updated", module_id, actor, ref=ref, **{"from": old.version, "to": new.version}
            )
            return UpdateResult(module_id, old.version, new.version, ref, rolled_back=False)
        self._restore(module_id, current, previous, stage_root / f"failed-{ref}", was_active)
        self._record("module.rolled_back", module_id, CORE_ACTOR, ref=ref, version=old.version)
        return UpdateResult(module_id, old.version, old.version, ref, rolled_back=True)

    def _restart(self, module_id: str, was_active: bool) -> bool:
        try:
            self._manager.reload(module_id)
        except Exception:
            return False
        if not was_active:
            return True
        self._manager.activate(module_id, actor=CORE_ACTOR)
        if self._manager.info(module_id).status is not ModuleStatus.ACTIVE:
            return False
        ok, _ = self._manager.health(module_id)
        return ok

    def _restore(self, module_id: str, current: Path, previous: Path, failed: Path, was_active: bool) -> None:
        self._manager.deactivate(module_id, actor=CORE_ACTOR, reason="rollback")
        shutil.rmtree(failed, ignore_errors=True)
        current.rename(failed)
        previous.rename(current)
        self._manager.reload(module_id)
        if was_active:
            self._manager.activate(module_id, actor=CORE_ACTOR)

    def rollback(self, module_id: str, *, actor: str) -> str:
        current = self._installed(module_id)
        stage_root = self._staging / module_id
        candidates = (
            sorted(stage_root.glob("previous-*"), key=lambda p: p.stat().st_mtime)
            if stage_root.exists()
            else []
        )
        if not candidates:
            raise UpdateError(f"no previous version of {module_id!r} to roll back to")
        previous = candidates[-1]
        was_active = self._manager.info(module_id).status is ModuleStatus.ACTIVE
        self._restore(
            module_id, current, previous, stage_root / f"replaced-{time.monotonic_ns()}", was_active
        )
        version = self._manager.manifest(module_id).version
        self._record("module.rolled_back", module_id, actor, version=version, reason="manual")
        return version
