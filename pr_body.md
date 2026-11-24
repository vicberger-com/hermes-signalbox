## Summary

Implements all 7 work packages from the H3 maintenance phase pre-work Q&A (docs/qa/17-h3-prework.md).

### Work Packages

| WP | Branch | Area | Findings | Status |
|---|---|---|---|---|
| WP1 | fix/h3-audit | Audit noise | H3-16, H3-17, H3-18, H3-21 | Done |
| WP2 | fix/h3-audit | Process hardening | H3-19, H3-24 | Done |
| WP3 | fix/h3-audit | API config | H3-20 | Done |
| WP4 | fix/h3-audit | T2 shutdown | H3-22 | Done |
| WP5 | fix/h3-audit | Error semantics | H3-23 | Done |
| WP6 | fix/h3-audit | Unix device paths | H3-25 | Done |
| WP7 | fix/h3-audit | README notes | H3-26, H3-27 | Done |

### Changes

**WP1 - Audit noise:**
- `src/switchyard/discovery.py`: T2 child process no longer writes `module.verified` audit (H3-16, H3-18, H3-21)
- `src/switchyard/core.py`: `resources.resolve` uses 5-minute audit window to reduce per-call overhead (H3-17)

**WP2 - Process hardening:**
- `src/switchyard/process.py`: Unix environment variable hardening equivalents (LD_PRELOAD, LD_LIBRARY_PATH, DYLD_INSERT_LIBRARIES, DYLD_LIBRARY_PATH, PYTHONPATH, PYTHONHOME, JAVA_TOOL_OPTIONS, SSH_AUTH_SOCK, GPG_AGENT_INFO, GPG_TTY, PINENTRY_USER_DATA, SSH_*, GPG_*, PINENTRY_* prefixes, _PATH, _LIBRARY_PATH suffixes)
- `system_program()` used for `taskkill` and `icacls` on Windows (H3-19)

**WP3 - API config:**
- `src/switchyard/api.py`, `src/switchyard/config.py`: `MAX_CONNECTIONS` and `REQUEST_READ_DEADLINE_S` now configurable via `config.toml` (H3-20)
- Updated tests in `tests/core/test_1_1_api_server.py`

**WP4 - T2 shutdown:**
- `src/switchyard/host_t2.py`: `shutdown_error` records exception detail, not just class name (H3-22)
- Updated test in `tests/core/test_1_1_hygiene.py`

**WP5 - Error semantics:**
- `src/switchyard/errors.py`: Added `ModuleNotRunning` and `BrokerUnavailableToSubprocess` subclasses of `NotAvailable` (H3-23)
- `src/switchyard/host_t2.py`, `src/switchyard/lifecycle.py`: Use new error classes

**WP6 - Unix device paths:**
- `src/switchyard/fsread.py`: Refuses `/dev/`, `/sys/`, `/proc/` paths on Unix (H3-25)

**WP7 - README notes:**
- `docs/USER-GUIDE.md`: Added security notes for challenge context versioning (H3-26) and Unix env var hardening (H3-27)

### Verification

- All tests pass (94.72% coverage)
- ruff clean
- mypy strict clean
- Bandit 0 findings
- pip-audit clean

### Related

- H3 evaluation: docs/qa/16-h3-eval-prework.md
- H3 pre-work Q&A: docs/qa/17-h3-prework.md (merged in #193)
- Closes H3-16 through H3-27
- Addresses H2-2, H2-3, H2-4 regressions