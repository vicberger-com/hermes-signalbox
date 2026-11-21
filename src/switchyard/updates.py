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

import contextlib
import json
import shutil
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from switchyard.capabilities import CORE_ACTOR, AuditSink
from switchyard.errors import ManifestError, SwitchyardError, UpdateError
from switchyard.gitfetch import (
    _CHANNEL as _CHANNEL,
)
from switchyard.gitfetch import (
    _GIT_ENV_ALLOW as _GIT_ENV_ALLOW,
)
from switchyard.gitfetch import (
    _SHA as _SHA,
)
from switchyard.gitfetch import (
    GIT_TIMEOUT_S as GIT_TIMEOUT_S,
)
from switchyard.gitfetch import (
    LS_REMOTE_TIMEOUT_S as LS_REMOTE_TIMEOUT_S,
)
from switchyard.gitfetch import (
    Fetcher as Fetcher,
)
from switchyard.gitfetch import (
    GitFetcher as GitFetcher,
)
from switchyard.gitfetch import (
    _check_ref as _check_ref,
)
from switchyard.gitfetch import (
    _force_remove as _force_remove,
)
from switchyard.gitfetch import (
    git_usable as git_usable,
)
from switchyard.gitfetch import (
    resolved_git as resolved_git,
)
from switchyard.lifecycle import ModuleManager, ModuleStatus
from switchyard.manifest import Manifest, load_manifest
from switchyard.sbom import (
    _CONTROL as _CONTROL,
)
from switchyard.sbom import (
    _SEMVER as _SEMVER,
)
from switchyard.sbom import (
    MAX_FILE_BYTES as MAX_FILE_BYTES,
)
from switchyard.sbom import (
    MAX_FILES as MAX_FILES,
)
from switchyard.sbom import (
    MAX_NOTES as MAX_NOTES,
)
from switchyard.sbom import (
    _declared as _declared,
)
from switchyard.sbom import (
    inventory as inventory,
)
from switchyard.sbom import (
    is_downgrade as is_downgrade,
)
from switchyard.sbom import (
    patch_notes as patch_notes,
)
from switchyard.sbom import (
    sbom_delta as sbom_delta,
)
from switchyard.sbom import (
    tree_digest as tree_digest,
)
from switchyard.sbom import (
    version_key as version_key,
)

KEEP_PREVIOUS = 3
CHECK_CACHE_SECONDS = 3600.0
CHECK_MIN_SECONDS = 60.0
# Files Python or the OS loader would run but nobody reviews as source (M12 review); extension modules and
# native libraries included, suffixes compared case-insensitively (H1 B-11).
_UNREVIEWABLE = (".pyc", ".pyo", ".pth", ".pyw", ".pyd", ".so", ".dylib", ".dll")


@dataclass(frozen=True)
class UpdateResult:
    id: str
    from_version: str
    to_version: str
    ref: str
    rolled_back: bool
    delta: dict[str, Any] | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "from": self.from_version, "to": self.to_version, "ref": self.ref,
                "rolled_back": self.rolled_back, "delta": self.delta, "notes": self.notes}  # fmt: skip


class UpdateController:
    def __init__(
        self,
        manager: ModuleManager,
        audit: AuditSink,
        data_dir: Path,
        fetcher: Fetcher,
        *,
        swap_guard: Callable[[], AbstractContextManager[Any]] | None = None,
    ) -> None:
        # H1 B-2: fetching and verifying run without the core lock; only the swap (and rollback, which has
        # no network) takes ``swap_guard``, which the core supplies as "core lock held and core still open".
        self._swap_guard = swap_guard or contextlib.nullcontext
        self._module_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._manager = manager
        self._audit = audit
        self._modules_dir = (data_dir / "modules").resolve()
        self._staging = data_dir / "staging"
        self._fetcher = fetcher
        self.fetcher = fetcher  # read-only use: config show reports the git it resolved
        self._checking = threading.Lock()
        self._check_state = threading.Lock()
        self._last_check: tuple[float, list[dict[str, Any]]] | None = None

    def _record(self, action: str, module_id: str, actor: str, **detail: str) -> None:
        self._audit.append(actor=actor, action=action, module=module_id, detail=detail)

    def _module_lock(self, module_id: str) -> threading.Lock:
        """One update, preview or rollback per module at a time."""
        with self._locks_guard:
            return self._module_locks.setdefault(module_id, threading.Lock())

    def _installed(self, module_id: str) -> Path:
        manifest = self._manager.manifest(module_id)
        if manifest.update_source != "git" or not manifest.update_url:
            raise UpdateError(f"module {module_id!r} is bundled; it updates with the Switchyard release")
        directory = manifest.directory.resolve()
        if directory.parent != self._modules_dir:
            raise UpdateError(f"module {module_id!r} is not installed under {self._modules_dir}")
        return directory

    def _stage(self, module_id: str, ref: str, actor: str) -> tuple[Path, Path, Manifest, Manifest]:
        """Fetch ``ref`` into staging and verify it; returns (current, stage, old, new)."""
        _check_ref(ref)
        current = self._installed(module_id)
        old = self._manager.manifest(module_id)
        stage_root = self._staging / module_id
        stage_root.mkdir(parents=True, exist_ok=True)
        stage = stage_root / f"stage-{ref}"
        shutil.rmtree(stage, ignore_errors=True)
        try:
            self._fetcher.fetch(old.update_url or "", ref, stage)
            links = [p for p in stage.rglob("*") if p.is_symlink()]
            if links:
                raise UpdateError(f"staged tree contains a symlink ({links[0].relative_to(stage)}); refused")
            hidden = [
                p for p in stage.rglob("*")
                if "__pycache__" in p.parts or p.suffix.lower() in _UNREVIEWABLE or ".so." in p.name.lower()
            ]  # fmt: skip
            if hidden:
                raise UpdateError(
                    "staged tree contains compiled or path files "
                    f"({hidden[0].relative_to(stage).as_posix()}); refused"
                )
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
        return current, stage, old, new

    def preview(self, module_id: str, ref: str, *, actor: str) -> dict[str, Any]:
        """Stage and verify ``ref`` without applying it: SBOM delta, patch notes and the tree digest to pass
        to ``update`` so exactly what was reviewed is what gets installed."""
        with self._module_lock(module_id):
            return self._preview(module_id, ref, actor)

    def _preview(self, module_id: str, ref: str, actor: str) -> dict[str, Any]:
        current, stage, old, new = self._stage(module_id, ref, actor)
        try:
            delta = sbom_delta(current, stage, old, new)
            notes = patch_notes(stage, new.version)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        self._record("module.update_previewed", module_id, actor, ref=ref, digest=delta["digest"])
        return {
            "id": module_id,
            "from": old.version,
            "to": new.version,
            "downgrade": is_downgrade(old.version, new.version),
            "ref": ref,
            "delta": delta,
            "notes": notes,
        }

    def update(
        self,
        module_id: str,
        ref: str,
        *,
        actor: str,
        digest: str | None = None,
        accept_wider: bool = False,
        allow_downgrade: bool = False,
    ) -> UpdateResult:
        with self._module_lock(module_id):
            return self._update(module_id, ref, actor, digest, accept_wider, allow_downgrade)

    def _update(
        self, module_id: str, ref: str, actor: str, digest: str | None, accept_wider: bool,
        allow_downgrade: bool = False,
    ) -> UpdateResult:  # fmt: skip
        current, stage, old, new = self._stage(module_id, ref, actor)
        stage_root = stage.parent
        try:
            delta = sbom_delta(current, stage, old, new)
            if digest is not None and digest != delta["digest"]:
                raise UpdateError("staged files differ from the previewed digest; refused")
            if delta["widens"] and not accept_wider:
                raise UpdateError(
                    "update widens what the module may do ("
                    + "; ".join(delta["widens"])[:300]
                    + "); review with module preview and pass accept_wider"
                )
            if is_downgrade(old.version, new.version) and not allow_downgrade:
                raise UpdateError(
                    f"{new.version} is older than the installed {old.version}; "
                    "pass allow_downgrade to install it"
                )
            notes = patch_notes(stage, new.version)
        except UpdateError as exc:
            shutil.rmtree(stage, ignore_errors=True)
            self._record("module.update_rejected", module_id, actor, ref=ref, reason=str(exc)[:300])
            raise
        (stage_root / f"sbom-{ref}.json").write_text(json.dumps(delta, indent=1), encoding="utf-8")
        try:
            with self._swap_guard():
                return self._swap(module_id, ref, actor, current, stage, old, new, delta, notes)
        finally:
            shutil.rmtree(stage, ignore_errors=True)  # gone after a successful swap; a leftover otherwise

    def _swap(
        self, module_id: str, ref: str, actor: str, current: Path, stage: Path, old: Manifest, new: Manifest,
        delta: dict[str, Any], notes: str,
    ) -> UpdateResult:  # fmt: skip
        stage_root = stage.parent
        # Staging and the checks above ran without the core lock (H1 B-2). Under it, refuse if the installed
        # module is no longer the one they compared against (replaced or removed meanwhile).
        try:
            unchanged = self._installed(module_id) == current and self._manager.manifest(module_id) == old
        except SwitchyardError:
            unchanged = False
        if not unchanged:
            reason = "the installed module changed while the update was staged; refused"
            self._record("module.update_rejected", module_id, actor, ref=ref, reason=reason)
            raise UpdateError(f"{reason}; run the update again")
        was_active = self._manager.info(module_id).status is ModuleStatus.ACTIVE
        previous = stage_root / f"previous-{old.version}-{time.strftime('%Y%m%dT%H%M%S')}-{time.time_ns()}"
        prior_ref = self.installed_ref(module_id)
        self._manager.deactivate(module_id, actor=actor, reason="update")
        current.rename(previous)
        try:
            if prior_ref:
                Path(f"{previous}.ref").write_text(prior_ref, encoding="utf-8")
            # What a later rollback restores must be what was set aside here (H1 B-13).
            Path(f"{previous}.digest").write_text(tree_digest(inventory(previous)), encoding="utf-8")
            stage.rename(current)
        except BaseException as exc:
            # H1 B-1: the live directory is gone or half-replaced. Put the previous version back as it was.
            self._undo_swap(module_id, current, previous, stage_root / f"failed-{ref}", was_active)
            self._record("module.rolled_back", module_id, CORE_ACTOR, ref=ref, version=old.version,
                         reason=f"swap failed: {type(exc).__name__}")  # fmt: skip
            raise UpdateError(f"update of {module_id!r} could not swap directories ({type(exc).__name__}); "
                              "the previous version is back") from None  # fmt: skip
        if self._restart(module_id, was_active):
            self._set_installed_ref(module_id, ref)
            self._prune(stage_root)
            self._record(
                "module.updated", module_id, actor, ref=ref, digest=delta["digest"],
                widens=";".join(delta["widens"])[:300], **{"from": old.version, "to": new.version},
            )  # fmt: skip
            return UpdateResult(module_id, old.version, new.version, ref, False, delta, notes)
        self._restore(module_id, current, previous, stage_root / f"failed-{ref}", was_active)
        self._record("module.rolled_back", module_id, CORE_ACTOR, ref=ref, version=old.version)
        return UpdateResult(module_id, old.version, old.version, ref, True, delta, notes)

    # channels and checks ----------------------------------------------------------------------------------

    def _ref_file(self, module_id: str) -> Path:
        return self._staging / module_id / "installed-ref"

    def _set_installed_ref(self, module_id: str, ref: str) -> None:
        self._ref_file(module_id).write_text(ref, encoding="utf-8")

    def installed_ref(self, module_id: str) -> str | None:
        path = self._ref_file(module_id)
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if _SHA.match(text):
                return text
        return self._manager.manifest(module_id).update_ref

    def check(self, module_id: str) -> dict[str, Any]:
        """Compare the installed commit with the head of the module's channel. Nothing is fetched or
        applied."""
        self._installed(module_id)
        m = self._manager.manifest(module_id)
        head = self._fetcher.latest(m.update_url or "", m.update_channel)
        current = self.installed_ref(module_id)
        return {"id": module_id, "channel": m.update_channel, "installed": current, "available": head,
                "update": head != current}  # fmt: skip

    def cached_checks(self, max_age_s: float = CHECK_CACHE_SECONDS) -> list[dict[str, Any]]:
        """For ``core.read`` callers: the last result if younger than ``max_age_s`` (at least
        ``CHECK_MIN_SECONDS``), otherwise a fresh check. One check at a time; a caller arriving during one
        gets the last result (M12 review)."""
        max_age_s = max(max_age_s, CHECK_MIN_SECONDS)
        with self._check_state:
            cached = self._last_check
        if cached is not None and time.monotonic() - cached[0] < max_age_s:
            return [dict(r) for r in cached[1]]
        rows = self.check_all()
        return rows

    def check_all(self) -> list[dict[str, Any]]:
        if not self._checking.acquire(blocking=False):
            with self._check_state:
                cached = self._last_check
            return [dict(r) for r in cached[1]] if cached else [{"error": "a check is already running"}]
        try:
            rows = self._check_all()
        finally:
            self._checking.release()
        with self._check_state:
            self._last_check = (time.monotonic(), rows)
        return [dict(r) for r in rows]

    def _check_all(self) -> list[dict[str, Any]]:
        out = []
        for info in self._manager.modules():
            m = self._manager.manifest(info.id)
            if m.update_source != "git" or not m.update_url:
                continue
            try:
                out.append(self.check(info.id))
            except UpdateError as exc:
                # Generic text: messages can carry local paths, and check results reach core.read modules.
                reason = "channel not found" if "not found" in str(exc) else "check failed"
                self._record("module.update_check_failed", info.id, CORE_ACTOR, reason=str(exc)[:300])
                out.append({"id": info.id, "channel": m.update_channel, "error": reason})
        return out

    def _restart(self, module_id: str, was_active: bool) -> bool:
        """Start the new version; any exception counts as a failed restart (H1 B-1)."""
        try:
            self._manager.reload(module_id)
            if not was_active:
                return True
            self._manager.activate(module_id, actor=CORE_ACTOR)
            if self._manager.info(module_id).status is not ModuleStatus.ACTIVE:
                return False
            ok, _ = self._manager.health(module_id)
            return ok
        except Exception:
            return False

    def _undo_swap(
        self, module_id: str, current: Path, previous: Path, failed: Path, was_active: bool
    ) -> None:
        if current.exists():  # the stage was moved in, then something after it failed
            shutil.rmtree(failed, ignore_errors=True)
            current.rename(failed)
        previous.rename(current)
        Path(f"{previous}.ref").unlink(missing_ok=True)
        Path(f"{previous}.digest").unlink(missing_ok=True)
        self._manager.reload(module_id)
        if was_active:
            self._manager.activate(module_id, actor=CORE_ACTOR)

    def _restore(self, module_id: str, current: Path, previous: Path, failed: Path, was_active: bool) -> None:
        self._manager.deactivate(module_id, actor=CORE_ACTOR, reason="rollback")
        shutil.rmtree(failed, ignore_errors=True)
        current.rename(failed)
        previous.rename(current)
        self._manager.reload(module_id)
        if was_active:
            self._manager.activate(module_id, actor=CORE_ACTOR)

    @staticmethod
    def _previous(stage_root: Path) -> list[Path]:
        """Previous versions, oldest first, ordered by the time recorded in the name (not mtime)."""

        def stamp(p: Path) -> int:
            tail = p.name.rsplit("-", 1)[-1]
            return int(tail) if tail.isdigit() else 0

        if not stage_root.exists():
            return []
        return sorted((p for p in stage_root.glob("previous-*") if p.is_dir()), key=stamp)

    def _prune(self, stage_root: Path) -> None:
        for old in self._previous(stage_root)[:-KEEP_PREVIOUS]:
            shutil.rmtree(old, onerror=_force_remove)
            Path(f"{old}.ref").unlink(missing_ok=True)
            Path(f"{old}.digest").unlink(missing_ok=True)

    def rollback(self, module_id: str, *, actor: str, accept_wider: bool = False) -> dict[str, Any]:
        """Restore the most recent previous version. Refused when its files changed since they were set aside;
        afterwards the health check runs (if the module was active) and its outcome is returned and audited
        (H1 B-13): ``{"id", "version", "ok", "detail"}``."""
        with self._module_lock(module_id), self._swap_guard():
            return self._rollback(module_id, actor, accept_wider)

    def _rollback(self, module_id: str, actor: str, accept_wider: bool) -> dict[str, Any]:
        current = self._installed(module_id)
        stage_root = self._staging / module_id
        candidates = self._previous(stage_root)
        if not candidates:
            raise UpdateError(f"no previous version of {module_id!r} to roll back to")
        previous = candidates[-1]
        try:
            delta = sbom_delta(current, previous, self._manager.manifest(module_id), load_manifest(previous))
        except ManifestError:
            raise UpdateError("the previous version's manifest is no longer valid") from None
        if delta["widens"] and not accept_wider:
            widens = "; ".join(delta["widens"])[:300]
            raise UpdateError(f"rolling back widens what the module may do ({widens}); pass accept_wider")
        digest_file = Path(f"{previous}.digest")
        if digest_file.is_file():
            if digest_file.read_text(encoding="utf-8").strip() != delta["digest"]:
                reason = "the previous version's files changed after it was set aside; refused"
                self._record("module.rollback_rejected", module_id, actor, reason=reason)
                raise UpdateError(reason)
            digest_state = "verified"
        else:
            digest_state = "unrecorded"  # set aside by 1.0.x
        sidecar = Path(f"{previous}.ref")
        prior = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else ""
        was_active = self._manager.info(module_id).status is ModuleStatus.ACTIVE
        self._restore(module_id, current, previous, stage_root / f"replaced-{time.time_ns()}", was_active)
        sidecar.unlink(missing_ok=True)
        digest_file.unlink(missing_ok=True)
        if _SHA.match(prior):
            self._set_installed_ref(module_id, prior)
        else:
            self._ref_file(module_id).unlink(missing_ok=True)
        version = self._manager.manifest(module_id).version
        ok, detail = True, "not active; health not checked"
        if was_active:
            try:
                active = self._manager.info(module_id).status is ModuleStatus.ACTIVE
                ok, health_detail = self._manager.health(module_id) if active else (False, "did not start")
            except Exception as exc:  # a failing check is a result here, not a crash
                ok, health_detail = False, type(exc).__name__
            detail = "health check passed" if ok else f"health check failed: {health_detail}"[:300]
        health = "ok" if ok else ("failed" if was_active else "not_checked")
        self._record("module.rolled_back", module_id, actor, version=version, reason="manual",
                     health=health, digest=digest_state)  # fmt: skip
        return {"id": module_id, "version": version, "ok": ok, "detail": detail}
