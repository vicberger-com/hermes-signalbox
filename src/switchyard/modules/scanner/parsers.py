"""Scanner command lines and output parsers (pure functions; tested on recorded outputs).

Every parser returns findings as ``{"rule", "severity", "path", "line", "title"}`` with bounded strings, and
never copies a matched secret: gitleaks runs with ``--redact`` and only its rule id and location are kept.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

SEVERITIES = ("info", "low", "medium", "high", "critical")
MAX_FINDINGS = 2000
MAX_OUTPUT = 20_000_000


class ParseError(ValueError):
    pass


def _sev(value: object, default: str = "medium") -> str:
    text = str(value or "").lower()
    mapping = {
        "error": "high",
        "warning": "medium",
        "note": "low",
        "unknown": "medium",
        "moderate": "medium",
        "negligible": "info",
    }
    text = mapping.get(text, text)
    return text if text in SEVERITIES else default


def _f(rule: object, severity: str, path: object, line: object, title: object) -> dict[str, Any]:
    return {
        "rule": str(rule or "")[:120],
        "severity": severity,
        "path": str(path or "")[:400],
        "line": line if isinstance(line, int) and not isinstance(line, bool) else 0,
        "title": " ".join(str(title or "").split())[:300],
    }


def _json(text: str) -> Any:
    if len(text) > MAX_OUTPUT:
        raise ParseError("output too large")
    try:
        return json.loads(text) if text.strip() else None
    except ValueError as exc:
        raise ParseError("output is not JSON") from exc


def parse_gitleaks(out: str) -> list[dict[str, Any]]:
    data = _json(out)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ParseError("gitleaks: expected a list")
    return [
        _f(d.get("RuleID"), "high", d.get("File"), d.get("StartLine"), d.get("Description"))
        for d in data
        if isinstance(d, dict)
    ]


def parse_bandit(out: str) -> list[dict[str, Any]]:
    data = _json(out)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ParseError("bandit: expected results")
    return [
        _f(
            r.get("test_id"),
            _sev(r.get("issue_severity")),
            r.get("filename"),
            r.get("line_number"),
            r.get("issue_text"),
        )
        for r in data["results"]
        if isinstance(r, dict)
    ]


def parse_pip_audit(out: str) -> list[dict[str, Any]]:
    data = _json(out)
    deps = data.get("dependencies") if isinstance(data, dict) else data
    if not isinstance(deps, list) or not all(isinstance(d, dict) for d in deps):
        raise ParseError("pip-audit: expected dependencies")
    found = []
    for dep in deps:
        for vuln in (dep.get("vulns") or []) if isinstance(dep, dict) else []:
            if isinstance(vuln, dict):
                fix = ", ".join(vuln.get("fix_versions") or [])
                found.append(
                    _f(
                        vuln.get("id"),
                        "high",
                        f"{dep.get('name')}=={dep.get('version')}",
                        0,
                        f"{dep.get('name')} {dep.get('version')} is vulnerable"
                        + (f"; fixed in {fix}" if fix else ""),
                    )
                )
    return found


def parse_osv(out: str) -> list[dict[str, Any]]:
    data = _json(out)
    if data is None:
        return []
    if not isinstance(data, dict):
        raise ParseError("osv-scanner: expected an object")
    found = []
    for result in data.get("results") or []:
        source = (result.get("source") or {}).get("path", "")
        for pkg in result.get("packages") or []:
            info = pkg.get("package") or {}
            for vuln in pkg.get("vulnerabilities") or []:
                found.append(
                    _f(
                        vuln.get("id"),
                        "high",
                        source,
                        0,
                        f"{info.get('name')} {info.get('version')}: {vuln.get('summary', '')}",
                    )
                )
    return found


def parse_semgrep(out: str) -> list[dict[str, Any]]:
    data = _json(out)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ParseError("semgrep: expected results")
    return [
        _f(
            r.get("check_id"),
            _sev((r.get("extra") or {}).get("severity")),
            r.get("path"),
            (r.get("start") or {}).get("line"),
            (r.get("extra") or {}).get("message"),
        )
        for r in data["results"]
        if isinstance(r, dict)
    ]


def parse_trivy(out: str) -> list[dict[str, Any]]:
    data = _json(out)
    if not isinstance(data, dict):
        raise ParseError("trivy: expected an object")
    found = []
    for result in data.get("Results") or []:
        target = result.get("Target", "")
        for vuln in result.get("Vulnerabilities") or []:
            found.append(
                _f(
                    vuln.get("VulnerabilityID"),
                    _sev(vuln.get("Severity")),
                    target,
                    0,
                    f"{vuln.get('PkgName')} {vuln.get('InstalledVersion')}: {vuln.get('Title', '')}",
                )
            )
        for mis in result.get("Misconfigurations") or []:
            found.append(_f(mis.get("ID"), _sev(mis.get("Severity")), target, 0, mis.get("Title")))
        for sec in result.get("Secrets") or []:  # rule and location only, never the match
            found.append(
                _f(
                    sec.get("RuleID"),
                    _sev(sec.get("Severity"), "high"),
                    target,
                    sec.get("StartLine"),
                    sec.get("Title"),
                )
            )
    return found


def _semgrep_argv(target: str, opts: dict[str, Any]) -> list[str]:
    return [
        "semgrep",
        "scan",
        "--json",
        "--metrics",
        "off",
        "--disable-version-check",
        "--config",
        str(opts.get("semgrep_config", "p/security-audit")),
        target,
    ]


# name -> (argv builder, parser, exit codes meaning "ran fine")
SCANNERS: dict[
    str,
    tuple[Callable[[str, dict[str, Any]], list[str]], Callable[[str], list[dict[str, Any]]], frozenset[int]],
] = {
    "gitleaks": (
        lambda t, o: [
            "gitleaks",
            "detect",
            "--no-git",
            "--redact",
            "--no-banner",
            "--source",
            t,
            "--report-format",
            "json",
            "--report-path",
            "-",
        ],
        parse_gitleaks,
        frozenset({0, 1}),
    ),
    "bandit": (lambda t, o: ["bandit", "-r", t, "-f", "json", "-q"], parse_bandit, frozenset({0, 1})),
    "pip-audit": (
        lambda t, o: ["pip-audit", "-f", "json", "--progress-spinner", "off", t],
        parse_pip_audit,
        frozenset({0, 1}),
    ),
    "osv-scanner": (
        lambda t, o: ["osv-scanner", "scan", "source", "--format", "json", "-r", t],
        parse_osv,
        frozenset({0, 1}),
    ),
    "semgrep": (_semgrep_argv, parse_semgrep, frozenset({0, 1})),
    "trivy": (lambda t, o: ["trivy", "fs", "--format", "json", "--quiet", t], parse_trivy, frozenset({0, 1})),
}
