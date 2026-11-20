"""Hermes plugin adapter: ``register(ctx)`` (spec section 3, Hermes adapter; DESIGN.md section 6).

A thin layer over ``Core.run``; the core never imports Hermes. What it registers:

* **Model tools** (toolset ``switchyard``): ``switchyard_modules`` (list, show, activate, deactivate,
  health), ``switchyard_audit`` (verify, tail), ``switchyard_host``. The model can **not** grant or revoke
  capabilities, change modes or remove modules: a prompt-injected model could otherwise widen its own access.
  Those stay on human-initiated paths.
* **Slash command** ``/switchyard <noun> <verb> [id] [key=value ...]``: every operation, for the user.
* **CLI command** ``hermes switchyard ...``: the full ``switchyard`` CLI against the plugin's data directory.
* **Idle task** ``switchyard-audit-verify`` (daily): re-verifies the audit chain.
* **Redaction patterns**: the redactor's default credential shapes that Hermes accepts (>= 2 literal chars).

Hosting: Hermes may run several processes (CLI, TUI, gateway) that all load this plugin. Only the process
that takes the data directory's host lock hosts modules; it starts ``auto`` modules and runs a daemon thread
calling ``Core.tick()`` every ``TICK_SECONDS`` (Hermes idle tasks are hour-scale, too coarse for triggers).
Other processes work on persistent state and refuse live operations.

Tool results are JSON strings ``{"ok", "result" | "error", "message"}``. Every exception is caught here:
Hermes would otherwise put the exception message into the model's context; only core-written messages are
safe. Under ``plugins.isolation: host`` Hermes skips CLI commands; tools and the slash command still work.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import re
import shlex
import threading
from pathlib import Path
from typing import Any

from switchyard.api import ControlServer
from switchyard.bridge import OBSERVER_HOOKS
from switchyard.capabilities import CORE_ACTOR
from switchyard.core import Core
from switchyard.errors import SwitchyardError
from switchyard.hermes.config_port import HermesConfigAdapter
from switchyard.hermes.delegation import make_provider
from switchyard.ops import MODEL_ACTOR, OPERATIONS, UsageError
from switchyard.secrets import DEFAULT_PATTERNS

ACTOR = MODEL_ACTOR  # model-initiated tool calls
USER_ACTOR = "hermes-user"  # the /switchyard slash command, typed by the user
TICK_SECONDS = 15.0
MODEL_TOOL_ACTIONS = ("list", "show", "activate", "deactivate", "health", "run")
_INT = re.compile(r"-?\d{1,18}")
_LITERAL_PREFIX = re.compile(r"[A-Za-z0-9_-]{2}")

_current: HermesAdapter | None = None
_current_lock = threading.Lock()


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


MODULES_SCHEMA = _schema(
    "switchyard_modules",
    "Inspect and run Switchyard modules. Actions: list, show, activate, deactivate, health, and run (a "
    "module's read-only action, named by 'name' with 'args'). Granting capabilities is a user decision made "
    "with /switchyard, not available here.",
    {
        "action": {"type": "string", "enum": list(MODEL_TOOL_ACTIONS)},
        "id": {"type": "string", "description": "module id (all actions except list)"},
        "name": {"type": "string", "description": "module action name (run only)"},
        "args": {"type": "object", "description": "module action arguments (run only)"},
    },
    ["action"],
)
AUDIT_SCHEMA = _schema(
    "switchyard_audit",
    "Verify the Switchyard audit hash chain or read recent audit records (names only, never secret values).",
    {"action": {"type": "string", "enum": ["verify", "tail"]}, "n": {"type": "integer", "minimum": 1}},
    ["action"],
)
HOST_SCHEMA = _schema("switchyard_host", "Show this host's Switchyard capacity profile.", {}, [])


_TRIM_FIELDS = ("output", "content", "stdout", "stderr", "result", "text")


class _DuplicateKeyError(ValueError):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Duplicate keys would be silently merged by re-encoding: leave such results alone (M8 review)."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKeyError("duplicate key")
        out[key] = value
    return out


def _bool_or_str(value: str) -> bool | str:
    return {"true": True, "false": False}.get(value.lower(), value)


def _ok(result: Any) -> str:
    return json.dumps({"ok": True, "result": result}, default=str)


def _error(exc: BaseException) -> str:
    message = str(exc) if isinstance(exc, SwitchyardError) else ""
    return json.dumps({"ok": False, "error": type(exc).__name__, "message": message})


class HermesAdapter:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        configured = ctx.get_config("data_dir", None)
        data_dir = Path(configured) if configured else None
        self.core = Core(
            data_dir=data_dir, hermes_dir=Path(ctx.state.data_dir), hermes_config=HermesConfigAdapter()
        )
        self._stop = threading.Event()
        self._server: ControlServer | None = None
        self._thread: threading.Thread | None = None

    # registration -------------------------------------------------------------------------------------

    def register(self) -> None:
        ctx = self.ctx
        ctx.register_tool("switchyard_modules", "switchyard", MODULES_SCHEMA, self.tool_modules,
                          description=MODULES_SCHEMA["description"])  # fmt: skip
        ctx.register_tool("switchyard_audit", "switchyard", AUDIT_SCHEMA, self.tool_audit,
                          description=AUDIT_SCHEMA["description"])  # fmt: skip
        ctx.register_tool("switchyard_host", "switchyard", HOST_SCHEMA, self.tool_host,
                          description=HOST_SCHEMA["description"])  # fmt: skip
        ctx.register_command(
            "switchyard",
            self.command,
            description="Switchyard control plane (all operations).",
            args_hint="<noun> <verb> [id] [key=value ...]",
        )
        ctx.register_cli_command(
            "switchyard",
            "Switchyard control plane",
            self._cli_setup,
            self._cli_handler,
            description="Run the switchyard CLI against this profile's data directory.",
        )
        ctx.register_idle_task("switchyard-audit-verify", self._idle_verify, interval_hours=24)
        for hook in sorted(OBSERVER_HOOKS):  # ADR-0004: one forwarder per hook; modules attach in the core
            ctx.register_hook(hook, self._forwarder(hook))
        ctx.register_middleware("llm_request", self._llm_request)
        ctx.register_hook("transform_terminal_output", self._transform_terminal)  # ADR-0008
        ctx.register_hook("transform_tool_result", self._transform_tool)
        if hasattr(ctx, "register_delegation_provider"):  # ADR-0007; Hermes builds without it are fine
            with contextlib.suppress(ImportError):
                ctx.register_delegation_provider(make_provider(self.core.bridge, self.core.hosting))
        patterns = [p for p in DEFAULT_PATTERNS if _LITERAL_PREFIX.match(p)]
        ctx.register_redaction_patterns(patterns)
        if self.core.hosting:
            self.core.manager.start_auto(actor=CORE_ACTOR)
            if self.core.config.api.enabled:  # M9: the dashboard tab talks to this loopback API
                try:
                    server = ControlServer(self.core, port=self.core.config.api.port, profile="dashboard")
                    server.start()
                    self._server = server
                except (OSError, SwitchyardError) as exc:  # a busy port must not stop the tick (M9 review)
                    self.core.audit.append(
                        actor=CORE_ACTOR,
                        action="api.start_failed",
                        module="",
                        detail={"error": type(exc).__name__},
                    )
            self._thread = threading.Thread(target=self._drive, name="switchyard-tick", daemon=True)
            self._thread.start()

    def _forwarder(self, name: str) -> Any:
        def forward(**kwargs: Any) -> Any:
            try:
                if not self.core.hosting:
                    return None
                self.core.bridge.dispatch_hook(name, kwargs)
                if name == "pre_llm_call":  # ADR-0006: a module gate may block the turn
                    reason = self.core.bridge.dispatch_gate(kwargs)
                    if reason:
                        return {"action": "block", "message": reason}
            except Exception as exc:  # never break a Hermes turn
                del exc
            return None

        forward.__name__ = f"switchyard_{name}"
        return forward

    def _transform_terminal(self, **kwargs: Any) -> str | None:
        try:
            if not self.core.hosting:
                return None
            meta = {
                "returncode": kwargs.get("returncode"),
                "task_id": kwargs.get("task_id"),
                "env_type": kwargs.get("env_type"),
                "tool_name": "terminal",
            }
            return self.core.bridge.dispatch_transform("terminal_output", kwargs.get("output"), meta)
        except Exception:  # never break a tool call
            return None

    def _transform_tool(self, **kwargs: Any) -> str | None:
        """Tool results are usually JSON: shorten long string fields (``output``, ``content``, ``stdout``,
        ``stderr``, ``result``, ``text``) and re-encode, so the result stays valid JSON."""
        try:
            result = kwargs.get("result")
            if not self.core.hosting or not isinstance(result, str):
                return None
            meta = {
                "tool_name": kwargs.get("tool_name"),
                "status": kwargs.get("status"),
                "task_id": kwargs.get("task_id"),
            }
            try:
                data = json.loads(result, object_pairs_hook=_no_duplicate_keys)
            except _DuplicateKeyError:
                return None
            except ValueError:
                return self.core.bridge.dispatch_transform("tool_result", result, meta)
            if not isinstance(data, dict):
                return None
            # one module call per tool result (M8 review): the longest eligible string field
            fields = [k for k in _TRIM_FIELDS if isinstance(data.get(k), str)]
            if not fields:
                return None
            key = max(fields, key=lambda k: len(data[k]))
            new = self.core.bridge.dispatch_transform("tool_result", data[key], meta)
            if new is None:
                return None
            data[key] = new
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return None

    def _llm_request(self, request: dict[str, Any], **context: Any) -> dict[str, Any] | None:
        """Hermes ``llm_request`` middleware: ``{"request": ...}`` only when a module changed the model."""
        try:
            if not self.core.hosting or not isinstance(request, dict):
                return None
            changed = self.core.bridge.dispatch_llm_request(request, context)
        except Exception:
            return None
        return {"request": changed} if changed is not None else None

    def driver_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _drive(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.core.tick()
            except Exception as exc:  # the driver must survive; record and continue
                self.core.audit.append(actor=CORE_ACTOR, action="core.tick_failed", module="",
                                       detail={"error": type(exc).__name__})  # fmt: skip

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.core.close()

    # model tools --------------------------------------------------------------------------------------

    def _call(self, noun: str, verb: str, params: dict[str, Any], actor: str = ACTOR) -> str:
        redact = self.core.redactor
        try:
            result = redact.redact_obj(self.core.run(noun, verb, params, actor=actor))
        except Exception as exc:
            return redact.redact(_error(exc))
        return _ok(result)

    def tool_modules(self, args: dict[str, Any], **_kw: Any) -> str:
        action = args.get("action")
        if action not in MODEL_TOOL_ACTIONS:
            return _error(UsageError(f"action must be one of {list(MODEL_TOOL_ACTIONS)}"))
        if action == "run":
            params = {"action": args.get("name")} | {k: v for k, v in args.items() if k in ("id", "args")}
            return self._call("module", "action", params)
        params = {k: v for k, v in args.items() if k == "id"}
        return self._call("module", str(action), params)

    def tool_audit(self, args: dict[str, Any], **_kw: Any) -> str:
        action = args.get("action")
        if action not in ("verify", "tail"):
            return _error(UsageError("action must be 'verify' or 'tail'"))
        params = {"n": args["n"]} if action == "tail" and "n" in args else {}
        return self._call("audit", str(action), params)

    def tool_host(self, args: dict[str, Any], **_kw: Any) -> str:
        return self._call("host", "profile", {})

    # human paths --------------------------------------------------------------------------------------

    def _help(self) -> str:
        lines = ["Usage: /switchyard <noun> <verb> [id] [key=value ...]"]
        lines += [f"  {n} {v}: {op.description}" for (n, v), op in sorted(OPERATIONS.items())]
        return "\n".join(lines)

    def command(self, raw_args: str) -> str:
        try:
            words = shlex.split(raw_args or "")
        except ValueError as exc:
            return f"error: {exc}"
        if len(words) < 2:
            return self._help()
        noun, verb, rest = words[0], words[1], words[2:]
        operation = OPERATIONS.get((noun, verb))
        if operation is None:
            return f"error: unknown operation '{noun} {verb}'"
        params: dict[str, Any] = {}
        extra: dict[str, Any] = {}  # key=value pairs that are not operation parameters go to an ``args`` dict
        for word in rest:
            if "=" not in word:
                if "id" in operation.params and "id" not in params:
                    params["id"] = word
                    continue
                if "action" in operation.params and "action" not in params:
                    params["action"] = word
                    continue
                return f"error: expected key=value, got {word!r}"
            key, _, value = word.partition("=")
            spec = operation.params.get(key)
            if spec is None and "args" in operation.params:
                extra[key] = int(value) if _INT.fullmatch(value) else _bool_or_str(value)
                continue
            if spec is not None and spec.kind is bool:
                params[key] = value.lower() in ("1", "true", "yes")
            elif spec is not None and spec.kind is int and _INT.fullmatch(value):
                params[key] = int(value)
            else:
                params[key] = value
        if extra:
            params["args"] = extra
        reply = json.loads(self._call(noun, verb, params, actor=USER_ACTOR))
        if not reply["ok"]:
            return f"error: {reply['message'] or reply['error']}"
        return json.dumps(reply["result"], indent=2, default=str)

    def _cli_setup(self, parser: argparse.ArgumentParser) -> None:
        # REMAINDER does not capture a leading option, so the CLI's global --json flag is declared here.
        parser.add_argument("--json", dest="switchyard_json", action="store_true", help="JSON output")
        parser.add_argument("switchyard_args", nargs=argparse.REMAINDER)

    def _cli_handler(self, args: argparse.Namespace) -> int:
        from switchyard.cli import main

        flags = ["--json"] if getattr(args, "switchyard_json", False) else []
        return main(["--data-dir", str(self.core.data_dir), *flags, *args.switchyard_args])

    def _idle_verify(self, run: Any) -> str:
        result = self.core.verify_audit()
        if result.ok:
            return f"audit ok ({result.records} records)"
        detail = {"reason": result.reason, "seq": str(result.first_bad_seq)}
        self.core.audit.append(actor=CORE_ACTOR, action="audit.verify_failed", module="", detail=detail)
        return f"audit FAILED at record {result.first_bad_seq}: {result.reason}"


def current() -> HermesAdapter:
    if _current is None:
        raise SwitchyardError("switchyard plugin is not registered")
    return _current


def shutdown() -> None:
    global _current
    with _current_lock:
        adapter, _current = _current, None
    if adapter is not None:
        adapter.close()


def register(ctx: Any) -> None:
    """Hermes plugin entry point."""
    global _current
    shutdown()
    adapter = HermesAdapter(ctx)
    adapter.register()
    with _current_lock:
        _current = adapter


atexit.register(shutdown)
