"""The operations table: one definition per ``(noun, verb)``, shared by the CLI, the control API and the
Hermes tools so every surface behaves the same (spec section 3, CLI and Control API).

Each operation declares typed parameters; ``validate`` rejects unknown, missing or mistyped parameters with
``UsageError`` (CLI exit 2, HTTP 400). ``offline`` marks operations that are safe to run directly against the
data directory when no daemon is running (they do not need a live module instance).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from switchyard.errors import SwitchyardError
from switchyard.hostinfo import profile

if TYPE_CHECKING:
    from switchyard.core import Core


class UsageError(SwitchyardError):
    """The operation or its parameters are invalid."""


# The actor the Hermes adapter uses for model-initiated tool calls. Human paths use other actors.
MODEL_ACTOR = "hermes"


@dataclass(frozen=True)
class Param:
    kind: type
    required: bool = True
    default: Any = None
    minimum: int | None = None
    maximum: int | None = None
    help: str = ""


@dataclass(frozen=True)
class Operation:
    noun: str
    verb: str
    description: str
    fn: Callable[[Core, dict[str, Any], str], Any]
    params: Mapping[str, Param] = field(default_factory=dict)
    offline: bool = False

    def validate(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(raw) - set(self.params)
        if unknown:
            raise UsageError(f"unknown parameter(s) {sorted(unknown)} for '{self.noun} {self.verb}'")
        out: dict[str, Any] = {}
        for name, spec in self.params.items():
            if name not in raw:
                if spec.required:
                    raise UsageError(f"missing parameter {name!r} for '{self.noun} {self.verb}'")
                out[name] = spec.default
                continue
            value = raw[name]
            if not isinstance(value, spec.kind) or (spec.kind is int and isinstance(value, bool)):
                raise UsageError(f"parameter {name!r} must be {spec.kind.__name__}")
            number = value if isinstance(value, int) else 0
            if spec.kind is int and (
                (spec.minimum is not None and number < spec.minimum)
                or (spec.maximum is not None and number > spec.maximum)
            ):
                raise UsageError(f"parameter {name!r} must be between {spec.minimum} and {spec.maximum}")
            out[name] = value
        return out


OPERATIONS: dict[tuple[str, str], Operation] = {}

ID = Param(str, help="module id")
CAP = Param(str, help="capability id")


def op(
    noun: str, verb: str, description: str, *, offline: bool = False, **params: Param
) -> Callable[..., Any]:
    def register(
        fn: Callable[[Core, dict[str, Any], str], Any],
    ) -> Callable[[Core, dict[str, Any], str], Any]:
        OPERATIONS[(noun, verb)] = Operation(noun, verb, description, fn, params, offline)
        return fn

    return register


def _info(core: Core, module_id: str) -> dict[str, Any]:
    info = core.manager.info(module_id)
    manifest = core.manager.manifest(module_id)
    return {
        "id": info.id,
        "version": info.version,
        "status": info.status.value,
        "mode": info.mode,
        "isolation": info.isolation,
        "error": info.error,
        "requested": sorted(manifest.requested),
        "granted": sorted(core.policy.granted(module_id)),
    }


@op("module", "list", "List every discovered module with status, mode and capabilities.", offline=True)
def _module_list(core: Core, p: dict[str, Any], actor: str) -> Any:
    return [_info(core, i) for i in core.manager.ids()]


@op(
    "module",
    "show",
    "Show one module, including its declared contributions and live panels.",
    offline=True,
    id=ID,
)
def _module_show(core: Core, p: dict[str, Any], actor: str) -> Any:
    manifest = core.manager.manifest(p["id"])
    return {
        **_info(core, p["id"]),
        "summary": manifest.summary,
        "license": manifest.license,
        "contributes": {k: list(v) for k, v in manifest.contributes.items()},
        "net_hosts": list(manifest.net_hosts),
        "secrets": list(manifest.secrets),
        "panels": core.panels.panels(p["id"]),
    }


@op("module", "grant", "Grant a requested capability to a module.", offline=True, id=ID, capability=CAP)
def _module_grant(core: Core, p: dict[str, Any], actor: str) -> Any:
    core.policy.grant(p["id"], p["capability"], actor=actor)
    return {"granted": sorted(core.policy.granted(p["id"]))}


@op("module", "revoke", "Revoke a capability from a module.", offline=True, id=ID, capability=CAP)
def _module_revoke(core: Core, p: dict[str, Any], actor: str) -> Any:
    core.policy.revoke(p["id"], p["capability"], actor=actor)
    return {"granted": sorted(core.policy.granted(p["id"]))}


@op("module", "mode", "Set activation mode: manual, auto or disabled.", offline=True, id=ID, mode=Param(str))
def _module_mode(core: Core, p: dict[str, Any], actor: str) -> Any:
    core.manager.set_mode(p["id"], p["mode"], actor=actor)
    return {"mode": core.manager.info(p["id"]).mode}


def _require_host(core: Core) -> None:
    if not core.hosting:
        raise SwitchyardError(
            "this process does not host modules; use the one that does (daemon or hosting Hermes session)"
        )


@op("module", "activate", "Start a module (needs the hosting process: daemon or Hermes session).", id=ID)
def _module_activate(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    core.manager.activate(p["id"], actor=actor)
    return _info(core, p["id"])


@op("module", "deactivate", "Stop a running module.", id=ID)
def _module_deactivate(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    core.manager.deactivate(p["id"], actor=actor)
    return _info(core, p["id"])


@op("module", "health", "Run a module's health check.", id=ID)
def _module_health(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    ok, detail = core.manager.health(p["id"])
    return {"ok": ok, "detail": detail}


@op("module", "panel", "Render one of a running module's panels as plain data.", id=ID, panel=Param(str))
def _module_panel(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    return core.panels.render(p["id"], p["panel"])


@op(
    "module", "remove", "Stop and forget a module; drops its grants and data unless keep_data is true.",
    offline=True, id=ID, keep_data=Param(bool, required=False, default=False),
)  # fmt: skip
def _module_remove(core: Core, p: dict[str, Any], actor: str) -> Any:
    core.manager.remove(p["id"], actor=actor, keep_data=p["keep_data"])
    return {"removed": p["id"]}


@op(
    "module", "action", "Run an action a running module registered (ADR-0002).", id=ID,
    action=Param(str, help="action name"), args=Param(dict, required=False, help="action arguments (JSON)"),
)  # fmt: skip
def _module_action(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    action = core.actions.get(p["id"], p["action"])
    if actor == MODEL_ACTOR and not action.read_only:
        raise SwitchyardError(f"action {action.name!r} is not read-only; run it from /switchyard or the CLI")
    raw = p["args"] or {}
    unknown = sorted(set(raw) - set(action.params))
    if unknown:
        raise UsageError(f"unknown argument(s) {unknown} for action {action.name!r}")
    args: dict[str, Any] = {}
    for name, kind in action.params.items():
        if name not in raw:
            continue
        value = raw[name]
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise UsageError(f"argument {name!r} must be {kind.__name__}")
        args[name] = value
    core.audit.append(actor=actor, action="module.action", module=p["id"], detail={"action": action.name})
    try:
        result = action.handler(**args)
    except TypeError as exc:
        if "missing" in str(exc) and "argument" in str(exc):
            raise UsageError(f"missing argument for action {action.name!r}") from None
        raise SwitchyardError(f"action {action.name!r} failed: TypeError") from None
    except SwitchyardError:
        raise
    except Exception as exc:
        raise SwitchyardError(f"action {action.name!r} failed: {type(exc).__name__}") from None
    try:
        text = json.dumps(result)
    except (TypeError, ValueError):
        raise SwitchyardError(f"action {action.name!r} returned data that is not JSON") from None
    return json.loads(core.redactor.redact(text))


@op("module", "update", "Update a git-installed module to a pinned commit; rolls back if it fails.",
    id=ID, ref=Param(str, help="full 40-character commit SHA"))  # fmt: skip
def _module_update(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    return core.updates.update(p["id"], p["ref"], actor=actor).to_dict()


@op("module", "rollback", "Restore the previous version of a git-installed module.", id=ID)
def _module_rollback(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    return {"id": p["id"], "version": core.updates.rollback(p["id"], actor=actor)}


@op("audit", "verify", "Verify the audit hash chain against the stored head anchor.", offline=True)
def _audit_verify(core: Core, p: dict[str, Any], actor: str) -> Any:
    result = core.verify_audit()
    return {
        "ok": result.ok,
        "records": result.records,
        "first_bad_seq": result.first_bad_seq,
        "reason": result.reason,
    }


@op("audit", "tail", "Show the most recent audit records.", offline=True,
    n=Param(int, required=False, default=20, minimum=1, maximum=1000))  # fmt: skip
def _audit_tail(core: Core, p: dict[str, Any], actor: str) -> Any:
    return core.audit_log.tail(p["n"])


@op("host", "profile", "Show the host profile used to pick capacity defaults.", offline=True)
def _host_profile(core: Core, p: dict[str, Any], actor: str) -> Any:
    return profile(data_dir=core.data_dir, override=core.config.host_profile).to_dict()


@op("config", "show", "Show the effective core configuration (no secret values exist in it).", offline=True)
def _config_show(core: Core, p: dict[str, Any], actor: str) -> Any:
    c = core.config
    return {
        "data_dir": str(core.data_dir),
        "api": {"enabled": c.api.enabled, "port": c.api.port},
        "log": {"level": c.log_level},
        "host": {"profile": c.host_profile},
    }


def lookup(noun: str, verb: str) -> Operation:
    operation = OPERATIONS.get((noun, verb))
    if operation is None:
        raise UsageError(f"unknown operation '{noun} {verb}'")
    return operation
