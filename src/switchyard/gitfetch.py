"""Fetching pinned module commits with git (split from ``updates.py``, 1.1 H1 B-25).

``GitFetcher`` runs ``git`` with a fixed argument list, a scrubbed environment, no hooks, https only, a
timeout, and checks ``HEAD == ref`` before removing ``.git``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from typing import Any, Protocol

from switchyard.errors import ChannelNotFound, UpdateError
from switchyard.process import find_runnable

_SHA = re.compile(r"[0-9a-f]{40}\Z")

GIT_TIMEOUT_S = 300

LS_REMOTE_TIMEOUT_S = 60  # a check reads one ref; a hung remote should not hold it for minutes (H1 B-2)

_GIT_ENV_ALLOW = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")


class Fetcher(Protocol):
    def fetch(self, url: str, ref: str, dest: Path) -> None: ...

    def latest(self, url: str, channel: str) -> str: ...


_CHANNEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")


def _check_ref(ref: str) -> None:
    if not isinstance(ref, str) or not _SHA.match(ref):
        raise UpdateError("ref must be a full 40-character lower-case commit SHA")


def resolved_git(git: str = "git", configured: str | None = None) -> str | None:
    """The git this process will run: ``configured`` (``[tools] git``) or the first runnable one on PATH."""
    return find_runnable(git, configured=configured)


def git_usable(git: str = "git", configured: str | None = None) -> bool:
    """True if this process can run git (H1 D-2: the first git on PATH may be one it may not execute)."""
    return resolved_git(git, configured) is not None


class GitFetcher:
    """Fetch one exact commit with the system ``git``. Used only by the core (T0)."""

    def __init__(
        self, *, git: str = "git", allow_file_protocol: bool = False, configured: str | None = None
    ) -> None:
        self._git = git
        self._configured = configured
        self._allow_file = allow_file_protocol
        self._exe: str | None = None

    def executable(self) -> str | None:
        """The resolved git, probed once per fetcher (and again after it stops working)."""
        if self._exe is None:
            self._exe = resolved_git(self._git, self._configured)
        return self._exe

    def _run(self, args: list[str], cwd: Path, timeout: float = GIT_TIMEOUT_S) -> str:
        exe = self.executable()
        if exe is None:
            where = "[tools] git" if self._configured else "PATH"
            raise UpdateError(f"no git this process can run was found ({where})")
        env = {k: v for k in _GIT_ENV_ALLOW if (v := os.environ.get(k)) is not None}
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    # never discover a repository (and its config) above the working directory (M12 review)
                    "GIT_CEILING_DIRECTORIES": str(cwd.resolve().parent)})  # fmt: skip
        protocol = "always" if self._allow_file else "never"
        cmd = [exe, "-c", f"protocol.file.allow={protocol}", "-c", "core.hooksPath=" + os.devnull, *args]
        try:
            # Fixed argv; url and ref are validated above; no shell.
            done = subprocess.run(  # noqa: S603 # nosec B603
                cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._exe = None  # look again next time
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
            out = self._run(["ls-remote", "--heads", "--", url, f"refs/heads/{channel}"], Path(empty),
                            timeout=LS_REMOTE_TIMEOUT_S)  # fmt: skip
        for line in out.splitlines():
            sha, _, name = line.partition("\t")
            if name == f"refs/heads/{channel}" and _SHA.match(sha):
                return sha
        raise ChannelNotFound(f"channel {channel!r} not found")


def _force_remove(
    func: Any, path: str, _exc: Any
) -> None:  # pragma: no cover - read-only git objects on Windows
    os.chmod(path, 0o700)
    func(path)
