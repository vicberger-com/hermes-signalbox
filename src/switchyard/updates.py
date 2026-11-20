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

import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from switchyard.capabilities import CORE_ACTOR, AuditSink
from switchyard.errors import ManifestError, UpdateError
from switchyard.lifecycle import ModuleManager, ModuleStatus
from switchyard.manifest import Manifest, load_manifest
from switchyard.process import find_program

_SHA = re.compile(r"[0-9a-f]{40}\Z")
GIT_TIMEOUT_S = 300
_GIT_ENV_ALLOW = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")


class Fetcher(Protocol):
    def fetch(self, url: str, ref: str, dest: Path) -> None: ...

    def latest(self, url: str, channel: str) -> str: ...


MAX_FILES = 5000
MAX_FILE_BYTES = 50_000_000
KEEP_PREVIOUS = 3
CHECK_CACHE_SECONDS = 3600.0
CHECK_MIN_SECONDS = 60.0
# Compiled or path-hook files are not reviewed as source; Python would run them (M12 review).
_UNREVIEWABLE = (".pyc", ".pyo", ".pth")
MAX_NOTES = 4000
_CHANNEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def inventory(root: Path) -> dict[str, str]:
    """SBOM of a module tree: every file's relative path and SHA-256 (``__pycache__`` skipped)."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or path.is_dir():
            continue
        if len(out) >= MAX_FILES:
            raise UpdateError(f"module tree has more than {MAX_FILES} files; refused")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise UpdateError(
                f"{path.relative_to(root).as_posix()} is larger than {MAX_FILE_BYTES} bytes; refused"
            )
        with path.open("rb") as fh:
            digest = hashlib.file_digest(fh, "sha256").hexdigest()
        out[path.relative_to(root).as_posix()] = digest
    return out


def tree_digest(inv: dict[str, str]) -> str:
    h = hashlib.sha256()
    for name in sorted(inv):
        h.update(f"{name}\0{inv[name]}\n".encode())
    return h.hexdigest()


def _declared(m: Manifest) -> dict[str, Any]:
    return {
        "version": m.version,
        "license": m.license,
        "license_class": m.license_class,
        "capabilities": sorted(m.requested),
        "net_hosts": sorted(m.net_hosts),
        "secrets": sorted(m.secrets),
        "isolation": m.isolation,
        "entry": f"{m.entry_module}:{m.entry_class}",
        "contributes": {k: sorted(v) for k, v in m.contributes.items() if v},
    }


def sbom_delta(old_dir: Path, new_dir: Path, old: Manifest, new: Manifest) -> dict[str, Any]:
    """What an update changes: files added, removed and changed, and every declared-permission difference.
    ``widens`` lists the changes that need the operator's explicit acceptance (ADR-0011)."""
    a, b = inventory(old_dir), inventory(new_dir)
    before, after = _declared(old), _declared(new)
    declared = {k: {"from": before[k], "to": after[k]} for k in before if before[k] != after[k]}
    widens = []
    for key in ("capabilities", "net_hosts", "secrets"):
        added = sorted(set(after[key]) - set(before[key]))
        if added:
            widens.append(f"{key}: {', '.join(added)}")
    for kind, names in after["contributes"].items():  # new hooks etc. run under grants already given
        added = sorted(set(names) - set(before["contributes"].get(kind, ())))
        if added:
            widens.append(f"contributes.{kind}: {', '.join(added)}")
    if before["isolation"] == "subprocess" and after["isolation"] != "subprocess":
        widens.append("isolation: in-process")
    if before["license_class"] != after["license_class"]:
        widens.append(f"license_class: {after['license_class']}")
    return {
        "files": {
            "added": sorted(set(b) - set(a)),
            "removed": sorted(set(a) - set(b)),
            "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
        },
        "declared": declared,
        "widens": widens,
        "digest": tree_digest(b),
    }


def patch_notes(root: Path, version: str) -> str:
    """The ``## [version]`` section of the staged tree's CHANGELOG.md, cleaned and capped; empty if absent.
    Written by the module's author: shown to the operator, never to the model."""
    path = root / "CHANGELOG.md"
    if not path.is_file() or path.is_symlink():
        return ""
    with path.open("rb") as fh:
        text = fh.read(1_000_000).decode("utf-8", errors="replace")
    heading = re.compile(rf"## (\[{re.escape(version)}\]|{re.escape(version)})(\s|\Z)")
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if out:
                break
            if heading.match(line):
                out.append(line)
            continue
        if out:
            out.append(line)
    notes = _CONTROL.sub("", "\n".join(out).strip())
    # Format characters (bidi overrides, zero-width) can make text read differently from what it is.
    return "".join(ch for ch in notes if unicodedata.category(ch) != "Cf")[:MAX_NOTES]


def _check_ref(ref: str) -> None:
    if not isinstance(ref, str) or not _SHA.match(ref):
        raise UpdateError("ref must be a full 40-character lower-case commit SHA")


def git_usable(git: str = "git") -> bool:
    """True if this process can run ``git`` (some sandboxed installs cannot)."""
    exe = find_program(git)
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
        exe = find_program(self._git)
        if exe is None:
            raise UpdateError("git executable not found")
        env = {k: v for k in _GIT_ENV_ALLOW if (v := os.environ.get(k)) is not None}
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    # never discover a repository (and its config) above the working directory (M12 review)
                    "GIT_CEILING_DIRECTORIES": str(cwd.resolve().parent)})  # fmt: skip
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

    def latest(self, url: str, channel: str) -> str:
        """The commit at the head of ``channel`` (``git ls-remote``); nothing is downloaded."""
        if not (url.startswith("https://") or (self._allow_file and url.startswith("file:"))):
            raise UpdateError("update URLs must use https://")
        if not _CHANNEL.match(channel) or ".." in channel:
            raise UpdateError("invalid channel name")
        with tempfile.TemporaryDirectory(prefix="switchyard-ls-") as empty:  # no repository config applies
            out = self._run(["ls-remote", "--heads", "--", url, f"refs/heads/{channel}"], Path(empty))
        for line in out.splitlines():
            sha, _, name = line.partition("\t")
            if name == f"refs/heads/{channel}" and _SHA.match(sha):
                return sha
        raise UpdateError(f"channel {channel!r} not found")


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
    delta: dict[str, Any] | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "from": self.from_version, "to": self.to_version, "ref": self.ref,
                "rolled_back": self.rolled_back, "delta": self.delta, "notes": self.notes}  # fmt: skip


class UpdateController:
    def __init__(self, manager: ModuleManager, audit: AuditSink, data_dir: Path, fetcher: Fetcher) -> None:
        self._manager = manager
        self._audit = audit
        self._modules_dir = (data_dir / "modules").resolve()
        self._staging = data_dir / "staging"
        self._fetcher = fetcher
        self._checking = threading.Lock()
        self._check_state = threading.Lock()
        self._last_check: tuple[float, list[dict[str, Any]]] | None = None

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
            hidden = [p for p in stage.rglob("*") if "__pycache__" in p.parts or p.suffix in _UNREVIEWABLE]
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
            "ref": ref,
            "delta": delta,
            "notes": notes,
        }

    def update(
        self, module_id: str, ref: str, *, actor: str, digest: str | None = None, accept_wider: bool = False
    ) -> UpdateResult:
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
            notes = patch_notes(stage, new.version)
        except UpdateError as exc:
            shutil.rmtree(stage, ignore_errors=True)
            self._record("module.update_rejected", module_id, actor, ref=ref, reason=str(exc)[:300])
            raise
        (stage_root / f"sbom-{ref}.json").write_text(json.dumps(delta, indent=1), encoding="utf-8")

        was_active = self._manager.info(module_id).status is ModuleStatus.ACTIVE
        previous = stage_root / f"previous-{old.version}-{time.strftime('%Y%m%dT%H%M%S')}-{time.time_ns()}"
        prior_ref = self.installed_ref(module_id)
        self._manager.deactivate(module_id, actor=actor, reason="update")
        current.rename(previous)
        if prior_ref:
            Path(f"{previous}.ref").write_text(prior_ref, encoding="utf-8")
        stage.rename(current)
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

    def rollback(self, module_id: str, *, actor: str, accept_wider: bool = False) -> str:
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
        sidecar = Path(f"{previous}.ref")
        prior = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else ""
        was_active = self._manager.info(module_id).status is ModuleStatus.ACTIVE
        self._restore(module_id, current, previous, stage_root / f"replaced-{time.time_ns()}", was_active)
        sidecar.unlink(missing_ok=True)
        if _SHA.match(prior):
            self._set_installed_ref(module_id, prior)
        else:
            self._ref_file(module_id).unlink(missing_ok=True)
        version = self._manager.manifest(module_id).version
        self._record("module.rolled_back", module_id, actor, version=version, reason="manual")
        return version
