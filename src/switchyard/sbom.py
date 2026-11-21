"""Module tree inventory, SBOM delta, patch notes and version order (split from ``updates.py``, 1.1).

H1 B-25: ``updates.py`` held fetching, the SBOM, channels and the swap in one class.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

from switchyard.errors import UpdateError
from switchyard.manifest import Manifest

MAX_FILES = 5000

MAX_FILE_BYTES = 50_000_000

MAX_NOTES = 4000

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


_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?\Z")


def version_key(version: str) -> tuple[Any, ...] | None:
    """Sort key for a manifest version (semver precedence: a pre-release sorts before its release, build
    metadata is ignored); ``None`` when the text is not of that form."""
    m = _SEMVER.match(version)
    if m is None:
        return None
    major, minor, patch, pre = m.groups()
    if pre is None:
        return (int(major), int(minor), int(patch), 1, ())
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (int(major), int(minor), int(patch), 0, ids)


def is_downgrade(old: str, new: str) -> bool:
    """True when ``new`` is an older version than ``old`` (H1 B-12). Unparseable versions never count."""
    a, b = version_key(old), version_key(new)
    return a is not None and b is not None and b < a


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
