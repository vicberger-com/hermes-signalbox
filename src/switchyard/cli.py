"""``switchyard`` command line (spec section 3, CLI).

``switchyard [--data-dir D] [--json] <noun> <verb> [id] [--param value ...]``. Subcommands are generated from
the shared operations table, so the CLI, the API and the Hermes tools cannot drift apart.

When a daemon is running for the data directory (``switchyard api serve``), every operation goes through it.
Otherwise operations marked ``offline`` run directly against the data directory; live operations (activate,
health, panels) need the daemon because a one-shot process cannot host a running module.

Exit codes: 0 success, 1 operation error, 2 usage error, 3 capability denied.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from switchyard import __version__
from switchyard.api import ApiClient, ApiUnavailable, ControlServer
from switchyard.core import Core
from switchyard.errors import CapabilityDenied, SwitchyardError
from switchyard.ops import OPERATIONS, Operation, UsageError

TICK_SECONDS = 1.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="switchyard", description="Hermes Switchyard control plane.")
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
        sub = groups[noun].add_parser(verb, help=operation.description, description=operation.description)
        for name, spec in operation.params.items():
            flag = "--" + name.replace("_", "-")
            if name == "id":
                sub.add_argument("id", help=spec.help or "module id")
            elif spec.kind is bool:
                sub.add_argument(flag, dest=name, action="store_true", help=spec.help)
            else:
                sub.add_argument(flag, dest=name, type=spec.kind, required=spec.required, help=spec.help)
    return parser


def _params(operation: Operation, args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, spec in operation.params.items():
        value = getattr(args, name, None)
        if value is None or (spec.kind is bool and value is False and not spec.required):
            continue
        out[name] = value
    return out


def _print(result: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    elif isinstance(result, list):
        for row in result:
            print("  ".join(f"{k}={v}" for k, v in row.items()) if isinstance(row, dict) else row)
    elif isinstance(result, dict):
        for key, value in result.items():
            print(f"{key}: {value}")
    elif result is not None:
        print(result)


def _serve(data_dir: Path | None, port: int | None) -> int:
    with Core(data_dir=data_dir) as core:
        server = ControlServer(core, port=port if port is not None else core.config.api.port)
        server.start()
        print(f"switchyard API listening on 127.0.0.1:{server.port} (token in {core.data_dir / 'api.token'})")
        try:
            core.manager.start_auto(actor="core")
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
        from switchyard.paths import resolve_data_dir

        resolved = resolve_data_dir()
    try:
        return ApiClient.from_data_dir(resolved).request(operation.noun, operation.verb, params)
    except ApiUnavailable:
        if not operation.offline:
            name = f"{operation.noun} {operation.verb}"
            raise SwitchyardError(
                f"'{name}' needs the running daemon: start it with 'switchyard api serve'"
            ) from None
    with Core(data_dir=resolved) as core:
        return core.run(operation.noun, operation.verb, params, actor="cli")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.noun is None:
        parser.print_help()
        return 2
    if args.noun == "version":
        print(__version__)
        return 0
    if args.noun == "api":
        return _serve(args.data_dir, args.port)
    operation = OPERATIONS[(args.noun, args.verb)]
    try:
        result = _run(operation, _params(operation, args), args.data_dir)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except CapabilityDenied as exc:
        print(f"denied: {exc}", file=sys.stderr)
        return 3
    except SwitchyardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print(result, args.json)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
