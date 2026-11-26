"""Validate Signalbox ``module.toml`` files. Thin CLI over ``hermes_signalbox.manifest``.

Usage: ``python tools/validate_manifest.py PATH [...]`` where PATH is a ``module.toml`` or a directory that is
searched recursively. Exit code 0 when every manifest is valid and every directory holds at least one.
Rules are documented in ``hermes_signalbox.manifest``; schema:
``src/hermes_signalbox/schemas/module.schema.json``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hermes_signalbox.manifest import check, cross_field, validate_document, validate_file

__all__ = ["check", "cross_field", "main", "validate_document", "validate_file"]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    failed = False
    files: list[Path] = []
    for name in argv:
        target = Path(name)
        found = sorted(target.rglob("module.toml")) if target.is_dir() else [target]
        if not found:
            failed = True
            print(f"INVALID {name}: no module.toml found")
        files.extend(found)
    for path in files:
        name = path.as_posix()
        errors = validate_file(path)
        if errors:
            failed = True
            print(f"INVALID {name}")
            for err in errors:
                print(f"  {err}")
        else:
            print(f"ok      {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
