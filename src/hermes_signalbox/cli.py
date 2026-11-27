"""``signalbox`` command line (spec section 3, CLI).

``hermes-signalbox [--data-dir D] [--json] <noun> <verb> [id]
[--param value ...]``. Subcommands are generated from the shared operations
table, so the CLI, the API and the Hermes tools cannot drift apart.

When a daemon is running for the data directory (``hermes-signalbox api
serve``), every operation goes through it.
Otherwise operations marked ``offline`` run directly against the data directory; live operations (activate,
health, panels) need the daemon because a one-shot process cannot host a running module.

Exit codes: 0 success, 1 operation error or a failed result (``status: failed``, ``ok: false``), 2 usage error
(including an unknown capability name), 3 capability denied. Operations marked ``[daemon]`` in ``--help`` need
``hermes-signalbox api serve`` (or a hosting Hermes session with the API enabled) for the same data directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

from hermes_signalbox import __version__, present
from hermes_signalbox.api import ApiClient, ApiRestricted, ApiUnavailable, ControlServer, clear_stale_files
from hermes_signalbox.core import Core
from hermes_signalbox.errors import PolicyRefused, SignalboxError
from hermes_signalbox.ops import OPERATIONS, Operation, UsageError

TICK_SECONDS = 1.0


class _Once(argparse.Action):
    """Stores one value. A second use of the option is an error: argparse would keep the last value and
    drop the first without a word, so ``--capability a --capability b`` granted only ``b``."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            parser.error(f"{option_string} was given more than once; run one command for each value")
        setattr(namespace, self.dest, values)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-signalbox", description="Hermes Signalbox control plane.")
    parser.add_argument(
        "--data-dir", type=Path, default=None, help="data directory (default: platform location)"
    )
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    nouns = parser.add_subparsers(dest="noun")
    nouns.add_parser("version", help="print the version")
    api = nouns.add_parser("api", help="loopback control API").add_subparsers(dest="verb", required=True)
    serve = api.add_parser("serve", help="run the daemon and the loopback API until interrupted")
    serve.add_argument("--port", type=int, default=None)

    groups: dict[str, Any] = {}
    for (noun, verb), operation in sorted(OPERATIONS.items()):
        if noun not in groups:
            groups[noun] = nouns.add_parser(noun, help=f"{noun} operations").add_subparsers(
                dest="verb", required=True
            )
        text = operation.description + ("" if operation.offline else " [daemon]")  # H1 D-7
        sub = groups[noun].add_parser(verb, help=text, description=text)
        for name, spec in operation.params.items():
            flag = "--" + name.replace("_", "-")
            if name == "id":
                sub.add_argument("id", help=spec.help or "module id")
            elif spec.kind is bool:
                sub.add_argument(flag, dest=name, action="store_true", help=spec.help)
            elif spec.kind is dict:
                sub.add_argument(
                    flag, dest=name, type=_json_object, required=spec.required, help=spec.help, action=_Once
                )
            else:
                sub.add_argument(
                    flag, dest=name, type=spec.kind, required=spec.required, help=spec.help, action=_Once
                )
    return parser


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a JSON object") from None
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return value


def _params(operation: Operation, args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, spec in operation.params.items():
        value = getattr(args, name, None)
        if value is None or (spec.kind is bool and value is False and not spec.required):
            continue
        out[name] = value
    return out


def _summaries(data_dir: Path | None) -> dict[str, str]:
    """Module descriptions for the text output, read from the manifests on disk (no daemon needed)."""
    try:
        with Core(data_dir=data_dir, hosting=False) as core:
            return {i: core.manager.manifest(i).summary for i in core.manager.ids()}
    except (SignalboxError, OSError):  # the list still prints, without the description column filled
        return {}


def _print(
    result: Any, as_json: bool, operation: Operation, data_dir: Path | None, prog: str, subject: str | None
) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    # H5 WP2 (#205): the same formatter as the chat reply, in plain text
    wants_names = (operation.noun, operation.verb) in (("module", "list"), ("report", "show"))
    summaries = _summaries(data_dir) if wants_names else {}
    text = present.render(
        operation.noun,
        operation.verb,
        result,
        style=present.TEXT,
        summaries=summaries,
        prog=prog,
        subject=subject,
        width=shutil.get_terminal_size((100, 24)).columns,
    )
    if result is not None:
        print(text)


def _failure(result: Any) -> str | None:
    """The message for a result that reports failure without raising (H1 D-8), else ``None``."""
    if not isinstance(result, dict):
        return None
    if result.get("status") == "failed":
        missing = result.get("missing_grants") or []
        need = f"; not granted: {', '.join(map(str, missing))}" if missing else ""
        return f"module {result.get('id')!r} failed: {result.get('error') or 'unknown error'}{need}"
    if result.get("ok") is False:
        return str(result.get("detail") or result.get("reason") or "the result reports ok: false")
    return None


def _stop(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt  # run the same clean shutdown as Ctrl+C


def _announce_waiting(skipped: dict[str, list[str]], prog: str) -> None:
    """#221: say which ``auto`` modules were not started and why. On stderr: stdout carries the readiness line
    that service managers parse."""
    for line in present.start_notice(skipped, prog):
        print(line, file=sys.stderr, flush=True)


def _serve(data_dir: Path | None, port: int | None) -> int:
    # H1 D-9: SIGTERM and Ctrl+Break (Windows) stop the daemon cleanly, so api.port and api.token are removed
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop)
    with Core(data_dir=data_dir, hosting=True) as core:
        server = ControlServer(core, port=port if port is not None else core.config.api.port)
        server.start()
        print(
            f"signalbox API listening on 127.0.0.1:{server.port} (token in {core.data_dir / 'api.token'})",
            flush=True,  # H1 D-26: service managers read this line through a pipe
        )
        try:
            _announce_waiting(core.manager.start_auto(actor="core"), "hermes-signalbox")
            while True:
                core.tick()
                time.sleep(TICK_SECONDS)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
    return 0


def _run(operation: Operation, params: dict[str, Any], data_dir: Path | None) -> Any:
    resolved = data_dir
    if resolved is None:
        from hermes_signalbox.paths import resolve_data_dir

        resolved = resolve_data_dir()
    hosted = False
    try:
        if clear_stale_files(resolved):  # nobody hosts this directory: no daemon to talk to (H1 D-9)
            raise ApiUnavailable(f"no running daemon for {resolved}")
        hosted = True
        return ApiClient.from_data_dir(resolved).request(operation.noun, operation.verb, params)
    except ApiRestricted:
        # 1.1 S-4: Hermes hosts this directory with the restricted API. Commands that need no daemon run on
        # the data directory, as they do when no daemon runs; the others keep the refusal, naming the routes.
        if not operation.offline:
            raise
    except ApiUnavailable:
        if not operation.offline:
            raise SignalboxError(_needs_host(operation, params, hosted)) from None
    # data_dir None: Core resolves the same directory itself, so config show reports the right source
    with Core(data_dir=data_dir, hosting=False) as core:
        return core.run(operation.noun, operation.verb, params, actor="cli")


def _needs_host(operation: Operation, params: dict[str, Any], hosted: bool) -> str:
    name = f"{operation.noun} {operation.verb}"
    if not hosted:
        return f"'{name}' needs the running daemon: start it with 'hermes-signalbox api serve'"
    # H4 R1-F5: another process (usually the Hermes gateway) hosts this directory with the API off, so
    # 'hermes-signalbox api serve' cannot start; name the steps that work in that setup
    target = params.get("id")
    chat = f"/signalbox {name}" + (f" {target}" if isinstance(target, str) else "")
    return (
        f"'{name}' runs in the process that hosts this data directory, and its API is off: run "
        f"'{chat}' in a Hermes chat, or set '[api] enabled = true' in config.toml in the data "
        "directory and restart Hermes"
    )


def main(argv: list[str] | None = None, *, prog: str = "hermes-signalbox") -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.noun is None:
        parser.print_help()
        return 2
    if args.noun == "version":
        print(__version__)
        return 0
    if args.noun == "api":
        try:
            return _serve(args.data_dir, args.port)
        except SignalboxError as exc:  # 1.1 S-7: a service manager logs one clear line, not a traceback
            print(f"error: {exc}", file=sys.stderr)
            return 1
    operation = OPERATIONS[(args.noun, args.verb)]
    try:
        params = _params(operation, args)
        result = _run(operation, params, args.data_dir)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PolicyRefused as exc:  # CapabilityDenied, or something the manifest did not declare (H1 A-31)
        print(f"denied: {exc}", file=sys.stderr)
        return 3
    except SignalboxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    subject = params.get("id") if isinstance(params.get("id"), str) else None
    _print(result, args.json, operation, args.data_dir, prog, subject)
    failure = _failure(result)
    if failure is not None:
        print(f"error: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
