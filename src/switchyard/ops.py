"""The operations table: one definition per ``(noun, verb)``, shared by the CLI, the control API and the
Hermes tools so every surface behaves the same (spec section 3, CLI and Control API).

Each operation declares typed parameters; ``validate`` rejects unknown, missing or mistyped parameters with
``UsageError`` (CLI exit 2, HTTP 400). ``offline`` marks operations that are safe to run directly against the
data directory when no daemon is running (they do not need a live module instance).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import switchyard
from switchyard.capabilities import CAPABILITIES
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.errors import UsageError as UsageError  # re-exported: older imports use switchyard.ops
from switchyard.hostinfo import profile
from switchyard.manifest import core_compatibility

if TYPE_CHECKING:
    from switchyard.core import Core


# The actor the Hermes adapter uses for model-initiated tool calls. Human paths use other actors.
MODEL_ACTOR = "hermes"
# What the model actor may run at all, enforced in the core (R1 review): the adapter's tool list is not the
# only guard. Module actions are further limited to read-only ones in run_action.
MODEL_OPS = frozenset(
    {
        ("module", "list"),
        ("module", "show"),
        ("module", "activate"),
        ("module", "health"),
        ("module", "action"),
        ("audit", "verify"),
        ("audit", "tail"),
        ("host", "profile"),
        ("report", "show"),
        ("config", "show"),
        ("module", "panel"),
    }
)


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
    # H1 B-2: False for operations that do network work (git) and take the core lock only where they need it
    locked: bool = True

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
    noun: str, verb: str, description: str, *, offline: bool = False, locked: bool = True, **params: Param
) -> Callable[..., Any]:
    def register(
        fn: Callable[[Core, dict[str, Any], str], Any],
    ) -> Callable[[Core, dict[str, Any], str], Any]:
        OPERATIONS[(noun, verb)] = Operation(noun, verb, description, fn, params, offline, locked)
        return fn

    return register


def _info(core: Core, module_id: str) -> dict[str, Any]:
    info = core.manager.info(module_id)
    manifest = core.manager.manifest(module_id)
    granted = core.policy.granted(module_id)
    return {
        "id": info.id,
        "version": info.version,
        "status": info.status.value,
        "mode": info.mode,
        "isolation": info.isolation,
        "error": info.error,
        "requested": sorted(manifest.requested),
        "granted": sorted(granted),
        # H1 D-8: what the module needs to start and does not hold yet
        "missing_grants": sorted(set(manifest.requested) - set(manifest.optional) - granted),
    }


def _known_capability(name: str) -> str:
    """An unknown capability name is a usage error (exit 2), not a denial (H1 D-26)."""
    if name not in CAPABILITIES:
        raise UsageError(f"unknown capability {name!r}; known: {', '.join(sorted(CAPABILITIES))}")
    return name


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
        # H1 B-10: what process.spawn may run; "any" is the blanket grant the prompt must show.
        "programs": ("any" if manifest.programs is None else list(manifest.programs))
        if "process.spawn" in manifest.requested
        else [],
        # H1 A-20: the 1.0 transition note ("outdated") for a module still on the old template's "<1"
        "requires_core": manifest.requires_core,
        "requires_core_note": core_compatibility(manifest.requires_core, switchyard.__version__)[1],
        "panels": core.panels.panels(p["id"]),
    }


@op("module", "grant", "Grant a requested capability to a module.", offline=True, id=ID, capability=CAP)
def _module_grant(core: Core, p: dict[str, Any], actor: str) -> Any:
    core.policy.grant(p["id"], _known_capability(p["capability"]), actor=actor)
    return {"granted": sorted(core.policy.granted(p["id"]))}


@op("module", "revoke", "Revoke a capability from a module.", offline=True, id=ID, capability=CAP)
def _module_revoke(core: Core, p: dict[str, Any], actor: str) -> Any:
    core.policy.revoke(p["id"], _known_capability(p["capability"]), actor=actor)
    stopped = False
    manifest = core.manager.manifest(p["id"])
    if (p["capability"] in manifest.requested and p["capability"] not in manifest.optional
            and core.manager.info(p["id"]).status.value == "active"):  # fmt: skip
        # Hooks, gates, middleware and jobs were registered under the old grant; stopping the module removes
        # them all (M6 review). Optional capabilities are checked at run time instead.
        core.manager.deactivate(p["id"], actor=actor, reason=f"revoked {p['capability']}")
        stopped = True
    return {"granted": sorted(core.policy.granted(p["id"])), "deactivated": stopped}


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
    mode = core.manager.info(p["id"]).mode
    if actor == MODEL_ACTOR and mode != "auto":
        # H1 C-6 (decision D8): a module the operator keeps manual or disabled is started by the operator only
        core.audit.append(actor=actor, action="policy.denied", module=p["id"],
                          detail={"operation": "module activate", "reason": f"mode {mode}"})  # fmt: skip
        raise CapabilityDenied(
            f"module {p['id']!r} is in {mode} mode: only the operator can start it (the model may start auto "
            "modules)"
        )
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
    if core.manager.info(p["id"]).status.value != "active":
        raise SwitchyardError(f"module {p['id']!r} is not active; start it with 'module activate {p['id']}'")
    return core.panels.render(p["id"], p["panel"])


@op(
    "module", "remove", "Stop and forget a module; drops its grants, and its data unless keep_data is true.",
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
    return run_action(core, p["id"], p["action"], p["args"] or {}, actor=actor,
                      read_only_only=actor == MODEL_ACTOR)  # fmt: skip


def _check_arguments(action: Any, args: Mapping[str, Any]) -> None:
    """A missing argument is found by binding to the handler's signature, not by reading a ``TypeError``
    message: a ``TypeError`` raised inside the handler is the handler failing (H1 B-25)."""
    try:
        inspect.signature(action.handler).bind(**args)
    except TypeError:
        raise UsageError(f"missing argument for action {action.name!r}") from None
    except ValueError:  # no signature available (some builtins): let the call decide
        pass


def call_action_handler(action: Any, args: Mapping[str, Any]) -> Any:
    """Run ``action.handler(**args)``; failures keep only the exception class (messages may carry data)."""
    _check_arguments(action, args)
    try:
        return action.handler(**args)
    except SwitchyardError:
        raise
    except Exception as exc:
        raise SwitchyardError(f"action {action.name!r} failed: {type(exc).__name__}") from None


def run_action(
    core: Core,
    module_id: str,
    name: str,
    raw: Mapping[str, Any],
    *,
    actor: str,
    read_only_only: bool,
    audit_detail: Mapping[str, str] | None = None,
    audit: bool = True,
) -> Any:
    """Validate and run one module action; shared by ``module action`` and ``ctx.call`` (ADR-0004).
    ``audit=False`` only for cross-module read-only calls the core records in aggregate (1.1 #124)."""
    action = core.actions.get(module_id, name)
    if read_only_only and not action.read_only:
        raise SwitchyardError(f"action {action.name!r} is not read-only; run it from /switchyard or the CLI")
    if not isinstance(raw, Mapping):
        raise UsageError("action arguments must be an object")
    p = {"id": module_id}
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
    if audit:  # before argument binding, so a refused call is recorded too (as in 1.0; 1.1 acceptance S3-5)
        detail = {"action": action.name, **(audit_detail or {})}
        core.audit.append(actor=actor, action="module.action", module=p["id"], detail=detail)
    result = call_action_handler(action, args)  # binds the arguments first (H1 B-25)
    try:
        json.dumps(result)
    except (TypeError, ValueError):
        raise SwitchyardError(f"action {action.name!r} returned data that is not JSON") from None
    # Redact the values, not the JSON text: escaping (quotes, backslashes, non-ASCII) would hide a match.
    return core.redactor.redact_obj(result)


@op("module", "update", "Update a git-installed module to a pinned commit; rolls back if it fails.",
    locked=False, id=ID, ref=Param(str, help="full 40-character commit SHA"),
    digest=Param(str, required=False, help="tree digest from module preview; refuses different files"),
    accept_wider=Param(bool, required=False, default=False,
                       help="accept new capabilities, hosts, secrets or weaker isolation"),
    allow_downgrade=Param(bool, required=False, default=False,
                          help="install a version older than the installed one"))  # fmt: skip
def _module_update(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    return core.updates.update(
        p["id"], p["ref"], actor=actor, digest=p.get("digest"), accept_wider=bool(p.get("accept_wider")),
        allow_downgrade=bool(p.get("allow_downgrade")),
    ).to_dict()  # fmt: skip


@op("module", "preview", "Stage a commit without applying it: SBOM delta, patch notes and tree digest.",
    locked=False, id=ID, ref=Param(str, help="full 40-character commit SHA"))  # fmt: skip
def _module_preview(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    return core.updates.preview(p["id"], p["ref"], actor=actor)


@op("module", "check_updates", "Compare git-installed modules with the head of their update channel.",
    locked=False)  # fmt: skip
def _module_check_updates(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    return {"modules": core.updates.check_all()}


@op("module", "rollback", "Restore the previous version of a git-installed module.", id=ID,
    accept_wider=Param(bool, required=False, default=False,
                       help="accept a previous version that may do more than the current one"))  # fmt: skip
def _module_rollback(core: Core, p: dict[str, Any], actor: str) -> Any:
    _require_host(core)
    return core.updates.rollback(p["id"], actor=actor, accept_wider=bool(p.get("accept_wider")))


@op("audit", "verify", "Verify the audit hash chain against the stored head anchor.", offline=True)
def _audit_verify(core: Core, p: dict[str, Any], actor: str) -> Any:
    result = core.verify_audit()
    return {
        "ok": result.ok,
        "records": result.records,
        "first_bad_seq": result.first_bad_seq,
        "reason": result.reason,
    }


@op("audit", "ack", "Acknowledge a recorded audit-chain failure after investigating it (operator only).",
    offline=True)  # fmt: skip
def _audit_ack(core: Core, p: dict[str, Any], actor: str) -> Any:
    return core.ack_audit(actor=actor)


@op("audit", "tail", "Show the most recent audit records.", offline=True,
    n=Param(int, required=False, default=20, minimum=1, maximum=1000))  # fmt: skip
def _audit_tail(core: Core, p: dict[str, Any], actor: str) -> Any:
    return core.audit_log.tail(p["n"])


@op("report", "show", "Operator report: health, usage, security or changes (redacted; M9).",
    kind=Param(str, required=True))  # fmt: skip
def _report_show(core: Core, p: dict[str, Any], actor: str) -> Any:
    from switchyard import reports

    if p["kind"] not in reports.KINDS:
        raise UsageError(f"kind must be one of {list(reports.KINDS)}")
    return core.redactor.redact_obj(reports.build(lambda n, v, q: core.run(n, v, q, actor=actor), p["kind"]))


@op("host", "profile", "Show the host profile used to pick capacity defaults.", offline=True)
def _host_profile(core: Core, p: dict[str, Any], actor: str) -> Any:
    return profile(data_dir=core.data_dir, override=core.config.host_profile).to_dict()


@op("config", "show", "Show the effective core configuration (no secret values exist in it).", offline=True)
def _config_show(core: Core, p: dict[str, Any], actor: str) -> Any:
    c = core.config
    return {
        "data_dir": str(core.data_dir),
        "data_dir_source": core.data_dir_source,
        "api": {"enabled": c.api.enabled, "port": c.api.port},
        "log": {"level": c.log_level},
        "host": {"profile": c.host_profile},
        # H1 D-2: which git the update operations run, and whether it was configured
        "tools": {"git_configured": c.git, "git": _git_in_use(core)},
    }


def _git_in_use(core: Core) -> str | None:
    executable = getattr(core.updates.fetcher, "executable", None)  # GitFetcher; test fetchers have none
    return executable() if callable(executable) else None


def lookup(noun: str, verb: str) -> Operation:
    operation = OPERATIONS.get((noun, verb))
    if operation is None:
        raise UsageError(f"unknown operation '{noun} {verb}'")
    return operation
