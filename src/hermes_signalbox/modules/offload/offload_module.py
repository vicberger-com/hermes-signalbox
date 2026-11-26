"""M11 offload connectors (spec: README.md in this directory).

Each connector declares its license class, the hosts or program it talks to, and the exact fields it sends.
``run {connector, payload}`` refuses any field outside that declaration (the data-sent declaration is
enforced, not documented only), and audits the connector and field names, never the values. Connectors that
are not open source are off until the operator allows them by name (``allow``). Only loopback hosts: the
manifest's ``net_hosts`` holds ``127.0.0.1`` and ``localhost``.

Settings, ``[modules.offload]``::

    allow = []                                     # connector names to enable besides open ones, e.g. ["n8n"]
    jevk5_url = "http://127.0.0.1:8090/v1/systemone"
    n8n_webhook = ""                               # e.g. "http://127.0.0.1:5678/webhook/<id>"
    timeout_seconds = 60                           # 5-600
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_signalbox.errors import SignalboxError

MAX_FIELD = 32_000
MAX_RESULT = 20_000
WORKDIR_PREFIX = "signalbox-offload-"
CLEANUP_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8)  # 1.1 #126: a CLI helper can hold the work dir for a moment
STALE_WORKDIR_S = 600
LOOPBACK = ("127.0.0.1", "localhost")


@dataclass(frozen=True)
class Connector:
    name: str
    license_class: str  # open | local | source-available | proprietary
    kind: str  # http | process
    target: str  # setting name holding the URL, or the program
    sends: tuple[str, ...]
    description: str


CONNECTORS = {
    c.name: c
    for c in (
        Connector(
            "jevk5",
            "local",
            "http",
            "jevk5_url",
            ("state", "questions", "kind"),
            "JevK5 typed decisions (local llama.cpp model): yes/no, choice and score answers.",
        ),
        Connector(
            "n8n",
            "source-available",
            "http",
            "n8n_webhook",
            ("task", "input"),
            "An n8n workflow webhook on this machine (n8n is fair-code, so it must be allowed by name).",
        ),
        Connector(
            "claude-code",
            "proprietary",
            "process",
            "claude",
            ("prompt",),
            "Claude Code CLI in print mode (prompt on stdin); uses the account it is logged in to.",
        ),
        Connector(
            "codex",
            "proprietary",
            "process",
            "codex",
            ("prompt",),
            "OpenAI Codex CLI in exec mode (prompt on stdin); uses the account it is logged in to.",
        ),
    )
}
OPEN_CLASSES = ("open", "local")
# Agent CLIs run without tools where the CLI allows it, in an empty working directory (M11 review): the
# declared data-sent limit only means something if the agent cannot read local files on its own. Claude Code:
# ``--tools ""`` disables every tool. Codex has no no-tools mode; its read-only sandbox can still read files,
# which the README states plainly, and the connector stays off until allowed by name.
ARGV = {
    "claude": ["claude", "-p", "--output-format", "text", "--tools", ""],
    "codex": ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"],
}


def _loopback_url(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise SignalboxError(f"[modules.offload] {key} must be text")
    if not value:
        return ""
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port  # raises on a bad port (M11 review)
    except ValueError:
        raise SignalboxError(f"[modules.offload] {key} is malformed") from None
    if (
        parts.scheme != "http"
        or parts.hostname not in LOOPBACK
        or parts.username
        or parts.password
        or "[" in parts.netloc
        or port == 0
    ):
        raise SignalboxError(f"[modules.offload] {key} must be an http://127.0.0.1 or http://localhost URL")
    return value


class OffloadModule:
    def __init__(self) -> None:
        self.ctx: Any = None
        self.settings: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stats: dict[str, list[int]] = {}

    def activate(self, ctx: Any) -> None:
        cfg = dict(ctx.config)
        known = {"allow", "jevk5_url", "n8n_webhook", "timeout_seconds"}
        if set(cfg) - known:
            raise SignalboxError(f"unknown [modules.offload] setting(s) {sorted(set(cfg) - known)}")
        allow = cfg.get("allow", [])
        if not isinstance(allow, list) or not set(allow) <= set(CONNECTORS):
            raise SignalboxError(f"[modules.offload] allow must list connectors from {sorted(CONNECTORS)}")
        timeout = cfg.get("timeout_seconds", 60)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 5 <= timeout <= 600:
            raise SignalboxError("[modules.offload] timeout_seconds must be an integer from 5 to 600")
        self.settings = {
            "allow": frozenset(allow),
            "jevk5_url": _loopback_url(
                cfg.get("jevk5_url", "http://127.0.0.1:8090/v1/systemone"), "jevk5_url"
            ),
            "n8n_webhook": _loopback_url(cfg.get("n8n_webhook", ""), "n8n_webhook"),
            "timeout_seconds": timeout,
        }
        ctx.register_action("connectors", self.connectors, params={}, read_only=True)
        ctx.register_action("report", self.report, params={}, read_only=True)
        ctx.register_action("run", self.run, params={"connector": str, "payload": str}, read_only=False)
        ctx.register_panel("offload.status", self.report)
        self.ctx = ctx

    def deactivate(self) -> None:
        self.ctx = None

    def health(self) -> tuple[bool, str]:
        return (self.ctx is not None, "running" if self.ctx is not None else "stopped")

    def enabled(self, connector: Connector) -> bool:
        return connector.license_class in OPEN_CLASSES or connector.name in self.settings["allow"]

    # actions ------------------------------------------------------------------------------------------

    def connectors(self) -> dict[str, Any]:
        out = []
        for c in CONNECTORS.values():
            where = (
                (self.settings.get(c.target) or "(not configured)")
                if c.kind == "http"
                else f"program {c.target}"
            )
            if c.kind == "http" and where != "(not configured)":
                parts = urllib.parse.urlsplit(where)
                where = f"{parts.scheme}://{parts.netloc}"  # never show paths: webhook ids are credentials
            out.append(
                {
                    "name": c.name,
                    "license_class": c.license_class,
                    "kind": c.kind,
                    "target": where,
                    "sends": list(c.sends),
                    "enabled": self.enabled(c),
                    "description": c.description,
                }
            )
        return {"connectors": out}

    def report(self) -> dict[str, Any]:
        with self._lock:
            stats = {k: {"runs": v[0], "failures": v[1]} for k, v in self._stats.items()}
        return {"runs": stats, "enabled": sorted(c.name for c in CONNECTORS.values() if self.enabled(c))}

    def run(self, connector: str, payload: str) -> dict[str, Any]:
        """Human-only: send ``payload`` (a JSON object) to ``connector``. Fields outside the connector's
        declaration are refused."""
        spec = CONNECTORS.get(connector)
        if spec is None:
            raise SignalboxError(f"unknown connector; choose from {sorted(CONNECTORS)}")
        if not self.enabled(spec):
            raise SignalboxError(
                f"connector {connector!r} is {spec.license_class}: allow it by name in "
                "[modules.offload] allow"
            )
        try:
            data = json.loads(payload)
        except ValueError as exc:
            raise SignalboxError("payload must be a JSON object") from exc
        if not isinstance(data, dict) or not data:
            raise SignalboxError("payload must be a non-empty JSON object")
        extra = set(data) - set(spec.sends)
        if extra:
            raise SignalboxError(f"{connector} may only receive {list(spec.sends)}; refused {sorted(extra)}")
        if len(json.dumps(data)) > MAX_FIELD * len(spec.sends):
            raise SignalboxError("payload too large")
        self.ctx.audit("offload", connector=connector, fields=",".join(sorted(data)))
        ok = False
        try:
            result = self._send(spec, data)
            ok = True
            return {"connector": connector, "result": result}
        finally:
            with self._lock:
                row = self._stats.setdefault(connector, [0, 0])
                row[0] += 1
                row[1] += 0 if ok else 1

    def _send(self, spec: Connector, data: dict[str, Any]) -> Any:
        timeout = self.settings["timeout_seconds"]
        if spec.kind == "http":
            url = self.settings[spec.target]
            if not url:
                raise SignalboxError(f"{spec.name}: set [modules.offload] {spec.target}")
            resp = self.ctx.net.request("POST", url, json=data, timeout=timeout)
            if resp.status >= 400:
                raise SignalboxError(f"{spec.name} answered HTTP {resp.status}")
            if resp.truncated:
                raise SignalboxError(f"{spec.name} answer too large")
            try:
                return resp.json()
            except SignalboxError:
                return resp.body[:MAX_RESULT]
        if not self.ctx.has("process.spawn"):
            raise SignalboxError(f"{spec.name} needs the process.spawn grant")
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise SignalboxError("prompt must be non-empty text")
        self._sweep_stale_workdirs()
        empty = tempfile.mkdtemp(prefix=WORKDIR_PREFIX)
        try:
            done = self.ctx.spawn.run(
                ARGV[spec.target], input=prompt, timeout=timeout, max_output=MAX_RESULT * 4, cwd=empty
            )
        finally:
            self._remove_workdir(empty, spec.name)
        if done.returncode != 0:
            raise SignalboxError(f"{spec.name} exited with {done.returncode}")
        return done.stdout[:MAX_RESULT]

    def _remove_workdir(self, path: str, connector: str) -> None:
        """Remove the empty working directory of a process run (1.1 #126). On Windows a child the CLI left
        running (Claude Code starts helpers) can still hold it; that must not fail a run whose program exited,
        so the failure is logged with the step and error class and the directory is left for the OS to clean.
        """
        error: OSError | None = None
        for delay in (*CLEANUP_RETRY_DELAYS, None):
            try:
                shutil.rmtree(path)
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                error = exc
            if delay is not None:
                time.sleep(delay)
        self.ctx.log("offload", "workdir_cleanup_failed", connector=connector, error=type(error).__name__,
                     path=path)  # fmt: skip

    @staticmethod
    def _sweep_stale_workdirs(now: float | None = None) -> None:
        """Remove empty working directories a held earlier run left behind. ``os.rmdir`` only removes empty
        directories, and only ones older than ``STALE_WORKDIR_S`` are tried, so a running offload is safe."""
        base = Path(tempfile.gettempdir())
        cutoff = (time.time() if now is None else now) - STALE_WORKDIR_S
        for entry in base.glob(f"{WORKDIR_PREFIX}*"):
            try:
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    os.rmdir(entry)
            except OSError:
                continue
