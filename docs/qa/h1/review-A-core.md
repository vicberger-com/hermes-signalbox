# Review A: core trust layer (hermes-switchyard v1.0.0)

> Published at the close of phase H1 (v1.0.1, 2026-11-20). Every High and Medium finding is fixed; the
> status of each finding is in [findings-index.md](findings-index.md). Findings still open in the 1.1 backlog are
> withheld (`withheld until fixed (#N)`) and are added when their issue closes. Probe scripts are not published.

Scope: `src/switchyard/{capabilities,context,secrets,audit,state,manifest,contract,lifecycle,core,config,paths,hostlock,errors}.py` and `src/switchyard/schemas/`. Read-only on the repo. Adjacent code read only where the in-scope code depends on it (`events.py`, `ops.py` grep, `host_t2_child.py` grep, `tools/validate_manifest.py` grep).
Probes: `<workstation>/switchyard-eval/probes/` (p01–p06), outputs in `../out-p0*.txt`. All data dirs were under `scratch/switchyard-eval/data/`. Probe canary values are synthetic.
Repo check: after the probes, no file under the repo is newer than the first probe file. `git status` returned nothing.

## Summary

- **No Critical or High findings.** Capability default-deny, the broker's leak guard, state confinement, and multi-process audit appends hold up under probing. The real problems are in the boundaries around them: entry resolution, the test/contract harness, result channels that skip redaction, and audit-log failure handling.
- Counts: Critical 0 · High 0 · **Medium 11** · **Low 13** · **Info 6** (30 findings; A-23 withdrawn).
- Several prework claims are only partly true: see "Against the prework" below.

## Findings

| ID | Sev | Confidence | Where | Summary |
|---|---|---|---|---|
| A-1 | Medium | confirmed-by-probe | paths.py:56-60; core.py:135-137; contract.py:23 | `SWITCHYARD_DATA_DIR` silently overrides an explicit `Core(data_dir=…)`. `run_contract` therefore writes into the operator's real data dir, despite its "touches nothing" docstring. |
| A-2 | Medium | confirmed-by-probe | capabilities.py:169-171, 173-194; audit.py:160-168 | A denial whose detail exceeds 1024 chars raises `AuditError`, not `CapabilityDenied`, and the `policy.denied` record is never written. |
| A-3 | Medium | confirmed-by-probe | manifest.py:205-215; lifecycle.py:289; host_t2_child.py:154 | The entry check validates `mod.py`, but import loads `mod/__init__.py` (a directory junction). Code that runs is not the code that was checked. T1 and T2. |
| A-4 | Medium | confirmed-by-probe | contract.py:130 | `run_contract` makes every module trusted. An in-process module outside the trusted roots gets a green contract that production discovery rejects. |
| A-5 | Medium | confirmed-by-probe | lifecycle.py:298-324; 416-428 | Manual `activate` runs module code (import, `activate`) with zero grants. The documented `granted` lifecycle step does not exist in code. |
| A-6 | Medium | confirmed-by-probe | capabilities.py:105-114, 159-165 | Stored grants survive a manifest that drops the capability. Restoring the manifest silently re-enables them, with no audit record. |
| A-7 | Medium | confirmed-by-probe | lifecycle.py:394-403; core.py:246-258 | `health()` detail (and any non-audit result) returns a secret value in plain text. The Redactor only guards audit and log writes. |
| A-8 | Medium | confirmed-by-probe | audit.py:243; audit.py:45 | `AuditLog.tail()` uses `str.splitlines()`. A detail containing U+2028/U+2029/U+0085 makes `audit tail` raise. A T2 module can trigger this. |
| A-9 | Medium | confirmed-by-probe | audit.py:115-118, 137-138; core.py:148-156 | Torn-tail handling: a benign crash is reported as tamper and needs `audit ack`. The docstring says opening fails closed; code swallows the error. A stripped final newline silently drops a record. |
| A-10 | Medium | confirmed-by-probe | core.py:139-145; state.py:78-84 | A failed `Core()` construction leaks the host lock. The same process can never host that data dir again. |
| A-11 | Medium | confirmed-by-reading | core.py:234-244 | `ack_audit` clears the broken flag and head anchor before the acknowledgement is written. If that append fails, the detected failure is forgotten. |
| A-12 | Low | confirmed-by-probe | audit.py:86-91, 264-266 | Invalid UTF-8 or deep JSON in the log raises `UnicodeDecodeError` / `RecursionError` out of `verify`. `Core()` cannot start and no status is reported. |
| A-13 | Low | confirmed-by-probe | audit.py:37, 135-143 | A complete last record larger than 64 KiB makes every append fail after restart. |
| A-14 | Low | confirmed-by-reading | audit.py:227, 215 | `os.write` return value unchecked; chain state advances on a short write. |
| A-15 | Low | confirmed-by-reading | capabilities.py:184-186, 198-199 | `require_host`/`require_secret` read `self._modules[...]` after the lock is released: `KeyError` if unregistered in between. |
| A-16 | Low | confirmed-by-reading | manifest.py:155-158; config.py:99-104 | Whole file read into memory before the size check. |
| A-17 | Low | confirmed-by-probe | secrets.py:89-90, 99-101 | `MemoryBackend`'s test-only guard is `"pytest" in sys.modules`; a stub module satisfies it. |
| A-18 | Low | confirmed-by-probe | secrets.py:209-216, 225 | Non-`KeyError` backend exceptions propagate unwrapped; a token in the backend's message reaches the caller. |
| A-19 | Low | confirmed-by-probe | manifest.py:148-150; capabilities.py:79-91, 107 | `validate_file` (and `tools/validate_manifest.py`) accept `contributes.policies` rules that discovery rejects. |
| A-20 | Low | confirmed-by-reading | manifest.py:187, 245 | `requires_core` is stored and never compared with the running core version. |
| A-21 | Low | confirmed-by-reading | contract.py:184; capabilities.py:162-164 | The contract's "grants gone" check is vacuous: `granted()` returns empty for any unregistered module, whatever the store holds. |
| A-22 | Low | confirmed-by-reading | context.py:424-436; lifecycle.py:326-331 | `ModuleContext.close()` is not exception-safe: a raise early on skips secret-backend and bridge cleanup. |
| A-23 | — | — | — | Withdrawn during review: not a finding (see the note under Details). |
| A-24 | Low | confirmed-by-reading | secrets.py:116-127 | Redactor value set grows without bound and is never cleared; each `redact()` scans every value. |
| A-25 | Low | confirmed-by-reading | state.py:263-286 | No storage quota for module tables or kv. A module can grow `state.db` until disk fills. |
| A-26 | Info | confirmed-by-reading | capabilities.py:170; m0-core.md §4 | `policy.denied` is listed as an event in the docs; it is only audited, never published to the bus. |
| A-27 | Info | confirmed-by-reading | context.py:242 | `ModuleContext.audit` truncates keys to 64 and values to 256 chars silently; two long keys with a common prefix collide. |
| A-28 | Info | confirmed-by-reading | state.py:229; m0-core.md §6 | Docs say CTEs are refused by the authorizer. Code allows `SQLITE_RECURSIVE`. Cost is still bounded by the work budget (P06b: 0.08 s) and the row cap. Docs need fixing. |
| A-29 | Info | confirmed-by-reading | context.py:99-100, 217, 381-412, 387; audit.py:127 | Typing: public `ctx.state`, `ctx.secrets`, `ctx.notify`, `ctx.hermes_config` return `object`; `ContextServices.audit`/`bridge` are `Any`; a `# type: ignore` covers a regex match. Module authors get no static types. |
| A-30 | Info | - | - | withheld until fixed (#96) |
| A-31 | Info | confirmed-by-reading | errors.py:8-38; secrets.py:47-52 | Error taxonomy: `SwitchyardError` is the catch-all for usage, state and policy-like errors; callers cannot separate them without string matching. |

### Details

**A-1 · Medium · confirmed-by-probe · paths.py:56-60, core.py:135-137, contract.py:23**
- Wrong: `resolve_data_dir` checks the env var first and returns it before the explicit argument. `Core(data_dir=X)` therefore ignores X whenever the variable is set.
- Evidence (P1): `Core(data_dir=argd).data_dir = …\data\p01-env-dir`; `state.db exists in arg dir: False | in env dir: True`; after `run_contract`, `env-dir audit files: ['audit-000001.jsonl']`, `env-dir state.db exists after contract: True`. Code: `override = env.get(ENV_VAR, "")` / `if override: return _absolute(...)` precedes `if configured is not None`.
- Impact: any programmatic caller or test that passes `data_dir` writes to the real store when the variable is set. The contract's `remove` step calls `drop_all()` and deletes grants in that same store (reasoned from code, not probed). The contract docstring promises it touches nothing outside its temp dir.
- Fix: explicit `data_dir` argument wins over the env var for `Core()`; the env var is honoured only by the CLI entry point. `run_contract` should pass an explicit env mapping that excludes the variable.
- Test: `SWITCHYARD_DATA_DIR=A`, `Core(data_dir=B)` → `B` used, `A` untouched; `run_contract` leaves `A` unchanged.

**A-2 · Medium · confirmed-by-probe · capabilities.py:169-171, 173-194; audit.py:160-168**
- Wrong: `_deny` appends `policy.denied` with the raw detail. `AuditLog._clean_detail` raises `AuditError` for any value over 1024 chars, before the write, so the exception that escapes is not `CapabilityDenied`.
- Evidence (P2): `control: short host, not granted -> CapabilityDenied`; `long host (2000 chars), not granted -> AuditError | is CapabilityDenied: False`; `long panel id, ui.panel not granted -> AuditError`; `policy.denied records written: 1` (expected 2 with the long cases recorded). Code: `if len(key) > MAX_NAME_CHARS or len(clean) > MAX_DETAIL_CHARS: raise AuditError(...)`.
- Impact: denial still fails closed, but the caller sees the wrong exception type, and the security record of the attempt is lost. A module controls the host and panel strings, so the attacker controls the loss of that record.
- Fix: truncate (with a length marker) in policy-generated detail rather than raising; always write the denial record.
- Test: `require_host(m, "h"*5000)` → `CapabilityDenied`, and a `policy.denied` record with a truncated value exists.

**A-3 · Medium · confirmed-by-probe · manifest.py:205-215; lifecycle.py:289; host_t2_child.py:154**
- Wrong: `_entry_file` checks `base.with_suffix(".py")` first and returns it after a resolve-inside check. Python's import system prefers a package directory `base/__init__.py` over `base.py`, so the code that runs is a different file.
- Evidence (P10): with `mod.py` inside the module dir and `mod/` a junction to `outside_pkg/` (`__init__.py`): `manifest loads: mod.py`; `discovered: ['jx']`; `activated; code that ran came from: OUTSIDE-JUNCTION`.
- Impact: the reviewed file (`mod.py`) is not what executes. This defeats the documented "entry inside the module directory" rule for T1 and T2 alike. Preconditions: write access to the module tree, which is inside the same-user boundary, so Medium not High. It matters most for trusted bundled modules, where a planted junction would run unreviewed code. Git updates refuse symlinks in staged trees (not checked in detail), but junctions are not covered by that check.
- Fix: after import, assert `sys.modules[name].__file__` resolves inside the module directory and equals the file that was checked. Or reject entries where both `X.py` and `X/` exist, and reject reparse points (symlinks and junctions) anywhere in the module tree.
- Test: module dir with a junction shadowing the entry → `load_manifest` or discovery rejects it.

**A-4 · Medium · confirmed-by-probe · contract.py:130**
- Wrong: the contract runs with `trusted_roots=[root]`, so every module, including one outside the bundled roots, is trusted for the run.
- Evidence (P12): an in-process module in a scratch dir: `run_contract ok: True []`; production discovery of the same module: `[]`.
- Impact: third-party authors get a passing report for a module that cannot start in a default install. The contract is the documented gate ("must pass before it ships").
- Fix: check the production trust rule in the contract (fail in-process modules outside the bundled roots unless the caller opts in with an explicit flag).
- Test: contract on an in-process module outside the trusted roots → FAIL at `discover` or a new `trust` check.

**A-5 · Medium · confirmed-by-probe · lifecycle.py:298-324 (vs 416-428)**
- Wrong: `ModuleManager.activate` never checks grants. `start_auto` does (`missing = sorted(e.manifest.requested - e.manifest.optional - self._policy.granted(...))`). `ModuleStatus` has no `granted` state, though m0-core.md §5 and DESIGN §5 describe `discovered → verified → granted → loaded → active`.
- Evidence (P13): `status with no grants: active`; `granted: []`.
- Impact: module code (imports, `activate`, background threads) runs before any consent. Brokers still deny capability use, so the blast radius is smaller. The documented consent order is not what the code does.
- Fix: refuse manual activation while requested, non-optional grants are missing (same rule as `start_auto`), or document the exception and add the `granted` state.
- Test: activate a module requesting `fs.read` with no grant → `SwitchyardError`, status unchanged.

**A-6 · Medium · confirmed-by-probe · capabilities.py:105-114, 159-165**
- Wrong: `register` replaces the in-memory manifest but never prunes the stored grants. `granted()` is `store ∩ requested − denied`, so the stored grant reappears as soon as the manifest requests the capability again.
- Evidence (P14): after narrowing, `granted: []`; after restoring the wide manifest, `granted: ['fs.read']`, with no new `policy.granted` record.
- Impact: consent given to version 1 of a module's capability comes back with version 3, with no audit record, even though the design says consent belongs to the installed code. An update that drops a capability and a later one that re-adds it gives it back silently. The update path (`accept_wider`) was not checked.
- Fix: on `register`, revoke (and audit `policy.revoked`) any stored grant whose capability is no longer requested or denied; or key grants by manifest hash.
- Test: register wide → grant → register narrow → register wide → `granted == ∅` and a `policy.revoked` record exists.

**A-7 · Medium · confirmed-by-probe · lifecycle.py:394-403; core.py:246-258; secrets.py:116-136**
- Wrong: the redactor is applied to audit and log writes only. `_normalise_health` returns the module's detail unchanged, and `Core.run` returns it to the caller.
- Evidence (P16): a module granted `secrets.read` returns the secret from `health()`: `health result: {'ok': True, 'detail': 'Zq9-canary-VALUE-7731'}`; `secret value present in health result: True`; `present in audit log text: False`. The guard works on the audit path; the health path skips it.
- Impact: DESIGN control 2 says the core "never returns it to a module result, a log or model context". This is a direct violation for `health`, and probably for panel and action results (not checked). Health is also exposed through the Hermes model tool (wrapping not checked). The trigger is a module returning a value it was granted, which is a trusted-module mistake, but the core is what should stop it.
- Fix: run health detail, panel renders and action results through `Redactor.redact_obj` before they leave `ModuleManager` / `Core.run`.
- Test: a module that returns a registered secret from `health()` → the result shows `[REDACTED]`.

**A-8 · Medium · confirmed-by-probe · audit.py:243, 45**
- Wrong: `tail()` splits the file with `str.splitlines()`. `_canonical` uses `ensure_ascii=False`, so U+2028, U+2029 and U+0085 are written raw inside records. `splitlines` treats them as line breaks.
- Evidence (P7): after appending a detail containing U+2028, `tail raised JSONDecodeError Expecting value`; `verify(): True`.
- Impact: `audit tail` (operator view, the contract's audit check, the `core.read` view) breaks on content one module wrote. A T2 module can do this through `ctx.audit` with no core-side gate.
- Fix: split on `\n` only (as `_iter_lines` does), or escape non-ASCII line-separator characters in `_canonical`.
- Test: a detail containing U+2028 → `tail()` returns that record.

**A-9 · Medium · confirmed-by-probe · audit.py:115-118, 137-138; core.py:148-156; audit.py:10 (docstring)**
- Wrong, three parts:
  1. A torn last line is the normal result of a crash mid-write, but `verify` reports it as `unparseable record`. `Core` then records `audit.verify_failed` and sets the broken flag, which needs `audit ack` (operator) to clear. A benign crash looks like tampering.
  2. The module docstring says "Opening a log whose last line is torn fails closed with AuditError". `AuditLog.__init__` catches `_TornTail` and continues with `head = (0, GENESIS)`.
  3. A complete record whose final `\n` was removed is accepted by `verify` (no newline requirement). The next append treats it as torn and quarantines it. The record is gone, and the mismatch surfaces only at the next restart.
- Evidence (P4): `head after reopen (no exception raised): (0, '0000…')`; `verify on torn log: False unparseable record`; `Core startup audit_status.ok = False`; `audit.verify_failed` at seq 3 (confirmed in the file). (The first attempt printed False only because my probe read `tail(10)`, which was too short.) (P5): `verify(anchor) after stripping final newline: True`; `seqs on disk after next append: [1, 2, 3, 4] | quarantine files: ['audit-000001.torn-…']`; `verify(anchor=3) after append: head anchor hash does not match`.
- Impact: operators learn to `audit ack` real tampering. A stripped newline removes a record without a verify failure at the time.
- Fix: distinguish "unterminated final line, never anchored" (benign, repair silently with a `torn_tail_repaired` record and no broken flag) from a mid-log failure. Require the final newline in `verify` so the stripped case fails at once. Correct the docstring or make `__init__` fail as documented.
- Test: torn tail → startup `audit_status.ok` stays True and no broken flag; newline stripped → `verify` fails.

**A-10 · Medium · confirmed-by-probe · core.py:139-145; state.py:78-84**
- Wrong: `Core.__init__` takes the host lock first, then runs the rest with no `try`. If `StateStore` construction fails, the lock is never released, and the SQLite connection is not closed on a failed pragma either.
- Evidence (P3): `first Core raised: OperationalError unable to open database file`; `second Core raised: SwitchyardError another process hosts modules for …` (same process, same dir, no other process).
- Impact: one failed startup disables hosting for that data dir for the life of the process (Hermes, tests, a retry loop). The error message also blames another process. The fd is held because `HostLock` has no `__del__` and nothing closes it.
- Fix: wrap the construction in `try`/`except BaseException: release everything, re-raise`, or use a context-manager/`ExitStack`.
- Test: `Core` construction with a corrupt store, then `Core(hosting=True)` on the repaired dir in the same process → succeeds.

**A-11 · Medium · confirmed-by-reading · core.py:234-244**
- Wrong: `ack_audit` deletes `audit.broken` and `audit.head` (lines 238 and 240) before it appends `audit.acknowledged` (line 241). Each `core_execute` autocommits, so a failure in between leaves no flag and no anchor.
- Evidence: code lines as above; `store` is opened with `isolation_level=None` (state.py:78).
- Impact: if the acknowledgement append fails (lock timeout, disk full), the detected truncation or edit is forgotten, and the next start verifies clean. This is the operator-acceptance step, so its failure should never clear the warning.
- Fix: do the append first, or run the three steps in one `BEGIN IMMEDIATE` transaction.
- Test: patch the append to raise → the broken flag and the anchor are still present afterwards.

**A-12 · Low · confirmed-by-probe · audit.py:86-91, 264-266**
- Wrong: `_iter_lines` decodes with the default strict UTF-8 and `verify_directory` catches only `ValueError`.
- Evidence (P6): `invalid utf-8: verify raised UnicodeDecodeError`; `Core startup raised UnicodeDecodeError`. (P19): a deep-JSON line in the middle of the log → `verify on middle deep-JSON line raised RecursionError`.
- Impact: one bad byte in the log stops `Core()` from starting, and the operator's own `audit verify` report crashes instead of saying what is wrong. Needs write access to the log (same-user boundary).
- Fix: catch `UnicodeDecodeError` and `RecursionError` in `verify_directory` (and decode with `errors="strict"` into a `VerifyResult`); the constructor should not raise on verify.
- Test: invalid byte and 100k-deep JSON in a mid-log record → `VerifyResult(ok=False, reason=…)`, no exception.

**A-13 · Low · confirmed-by-probe · audit.py:37, 135-143**
- Wrong: `_recover` reads only the last 64 KiB and assumes the last record fits. A larger complete record makes `json.loads` fail, which raises `AuditError` (not `_TornTail`), so repair never runs.
- Evidence (P9): one record of 81,294 bytes; after restart: `append after restart raised AuditError … last record is unreadable`.
- Impact: the audit log stops accepting writes until someone repairs it by hand. Reachability: `ModuleContext.audit` is capped at 16 fields (context.py:236), so modules cannot reach this size. Core callers were not checked in full (bridge.py, hermesconfig.py build detail dicts). The R1 claim "torn last line made every append fail — Fixed" covers the torn case only.
- Fix: cap record size in `AuditLog.append` (and field count), and make `_recover` read until a newline is found, not a fixed 64 KiB.
- Test: append a 100 KB-detail record → reopen → append succeeds.

**A-14 · Low · confirmed-by-reading · audit.py:227, 215**
- Wrong: `os.write(fd, line)` is not checked against its return value or looped. `_emit` then advances `_seq`/`_prev` (line 215) on a short write.
- Impact: a short write (rare: disk pressure) leaves a partial record in the middle of the log, and the next append builds on it. `verify` then fails on the next start.
- Fix: loop until the whole buffer is written; raise `AuditError` on zero progress.
- Test: a fake `os.write` that writes half → `AuditError`, state unchanged.

**A-15 · Low · confirmed-by-reading · capabilities.py:184-186, 198-199**
- Wrong: `require_host` calls `self.require(...)`, releases the lock, then reads `self._modules[module_id]`. An `unregister` in between raises a bare `KeyError`, not `CapabilityDenied`.
- Impact: the request still fails, but with an error type callers do not handle. Also the usual check-then-act window, bounded per call by `_Guarded`.
- Fix: do the lookup and the check under one lock hold (RLock makes that simple), or use `.get` and deny.
- Test: concurrent `unregister` during `require_host` → `CapabilityDenied` only.

**A-16 · Low · confirmed-by-reading · manifest.py:155-158; config.py:99-104**
- Wrong: `path.read_bytes()` loads the whole file before `len(raw) > MAX_*_BYTES`. The limit is applied after the memory is spent.
- Impact: a large `module.toml` or `config.toml` exhausts memory before rejection. Same-user, low likelihood.
- Fix: `os.stat` first, or read at most `MAX+1` bytes.
- Fixed in 1.1 (#89): both files are read through `paths.read_limited`, which reads at most the limit plus one byte.

**A-17 · Low · confirmed-by-probe · secrets.py:89-90, 99-101**
- Wrong: `_running_under_pytest()` is `"pytest" in sys.modules`.
- Evidence (P15): `outside pytest refused: SwitchyardError`; after `sys.modules['pytest'] = stub`, `MemoryBackend` is built and returns the stored value.
- Impact: a test backend (plain dict) can be enabled in production by any code that touches `sys.modules`. In-process modules are trusted anyway, so this is a tripwire, not a control.
- Fix: require an explicit `allow_test_backend=True` only, or remove the class from the production import path.
- Fixed in 1.1 (#90): the flag is the only way in.

**A-18 · Low · confirmed-by-probe · secrets.py:209-216, 225**
- Wrong: `_resolve` catches `KeyError` only. Other exceptions from `backend.get` propagate raw, outside `use()`'s `try`, so the message is not reduced to a class name.
- Evidence (P21): `caller got OSError message: keyring unlock failed; token=TOKEN-ABCDEFGH-12345 for api_key`. (The token is my synthetic value.)
- Impact: a backend that puts the value in its error text leaks it to the caller. The caller is in-process here; through a T2 host only the class crosses. Also contradicts the docs' "messages never carry secret values".
- Fix: wrap `backend.get`/`available` errors as `SecretUnavailable` with the class name only, and audit `secret.backend_error`.
- Test: backend raises with the value in the message → caller sees the class name only.

**A-19 · Low · confirmed-by-probe · manifest.py:148-150; capabilities.py:79-91, 107**
- Wrong: `policies` grammar is enforced only in `parse_policies`, called from `PolicyEngine.register`. `validate_document` (used by `validate_file` and `tools/validate_manifest.py`) does not check it.
- Evidence (P11): `validate_file errors: []`; `discovered by Core: []`.
- Impact: the validator says valid for a module that cannot load. CI using the validator misses it.
- Fix: call `parse_policies`-equivalent grammar checks from `cross_field`, and have the validator use them.
- Test: `policies = ["allow:fs.read"]` → `validate_file` returns an error.

**A-20 · Low · confirmed-by-reading · manifest.py:187, 245**
- Wrong: `requires_core` is stored on `Manifest` and never compared with the running version. grep finds no other use.
- Impact: a module that says it needs core `>=99` loads anyway. Compatibility is not enforced.
- Fix: check it against `switchyard.__version__` (or document the field as informational and drop it from the schema).
- Fixed in 1.1 (#91), per Q-SY-1.1-3 (a): `requires_core` is parsed at load (unreadable specs are manifest errors) and compared with the core at discovery, reload and update staging. A mismatch refuses the module. The exception, until core 2.0: when the only failing clause is the old template's `<1`, the module loads with an audited `module.requires_core_outdated` and a note in `module show`. The bundled modules and the template now declare `>=1.0,<2`.

**A-21 · Low · confirmed-by-reading · contract.py:184; capabilities.py:118, 162-164**
- Wrong: the contract's "grants gone" check is `not core.policy.granted(mid)`. After `remove`, the module is unregistered, so `granted()` returns empty whatever the store holds.
- Impact: the check cannot fail. A regression in `unregister` would pass the contract.
- Fix: query the store directly (`SqliteGrantStore.load`).

**A-22 · Low · confirmed-by-reading · context.py:424-436; lifecycle.py:326-331**
- Wrong: `ModuleContext.close()` sets `_closed` first and runs its steps in sequence with no `try`. An exception in `panels.remove_all` or `bus.unsubscribe_all` skips `secret_backends.remove_backends` and `bridge.remove_all`.
- Impact: a secret backend provided by a deactivated module can stay registered. Low likelihood, but it is the cleanup path.
- Fix: run each step in `try`/`except` and aggregate, or use `contextlib.ExitStack`.

**A-23 · (retracted)** Checked during the review and not a finding: unregistered modules are denied by default (`granted()` returns empty). Kept only so the IDs are contiguous.

**A-24 · Low · confirmed-by-reading · secrets.py:116-127**
- Wrong: `Redactor._values` is a set that `add` grows and nothing clears. Every `redact()` (every log line, every audit record) iterates the full set.
- Impact: memory and CPU grow with each distinct secret used in the process lifetime. Secrets stay in process memory after use.
- Fix: bounded LRU of recent values, or clear on `remove_backends`.
- Fixed in 1.1 (#92): bounded LRU of 256 values, and a removed backend's values are forgotten.

**A-25 · Low · confirmed-by-reading · state.py:205-224, 263-274**
- Wrong: `execute` (INSERT), `kv_set` and `create_table` have no size or count limit.
- Impact: a module can grow `state.db` until the disk fills. The work budget bounds CPU per statement, not storage.
- Fix: per-module quota checked on write, or a documented cap.
- Fixed in 1.1 (#93): values are capped at 4 MiB with SQLite's length limit during module statements (which also covers `zeroblob`/`randomblob`) and in `kv_set`. A module may have at most 64 tables and 256 MiB over its tables and kv rows. Usage is measured with dbstat, or summed lengths where dbstat is missing, on `create_table` and after each 1 MiB of database growth. Over the quota, inserts, updates and kv writes are refused until the module deletes data.

**A-26 · Info · confirmed-by-reading · capabilities.py:170; m0-core.md §4**
- The docs list `policy.denied` among the events. `PolicyEngine` has no bus reference, so the event is only audited. Either publish it or fix the docs.

**A-27 · Info · confirmed-by-reading · context.py:242**
- `clean = {str(k)[:64]: str(v)[:256] for ...}` silently collapses keys that match in their first 64 characters, and truncates values without a marker.
- Fixed in 1.1 (#94): names over 64 characters keep an 8-character digest of the whole name; cut values end in `[truncated]`.

**A-28 · Info · confirmed-by-probe · state.py:229; m0-core.md §6**
- Docs: "CTEs were already refused by the authorizer". Code: `if action in (SQLITE_SELECT, SQLITE_RECURSIVE): return OK`.
- Evidence (P17): `WITH RECURSIVE c(n) AS (…) SELECT n FROM c` → `[(1,), …, (5,)]`. CPU-bound CTE (P06b): `module query exceeded its work budget 0.08 s`. Some CTE forms are denied (`count(*)` over a CTE → `access denied to table 'c'`), which is inconsistent. Safety holds through the budget and the row cap, but the doc is wrong.

**A-29 · Info · confirmed-by-reading · context.py:99-100, 217, 381-412; audit.py:127**
- The public module-facing types are `object` (`ctx.state`, `ctx.secrets`, `ctx.notify`, `ctx.hermes_config`), and `ContextServices.audit`/`bridge` are `Any`. A `# type: ignore[union-attr]` covers a regex match that cannot fail (`_FILE_RE` is checked on the same name first). mypy cannot check module code against these APIs.
- Fix: return `ModuleSecrets`, `ModuleState`, etc., with Protocols for the optional ports.
- Fixed in 1.1 (#95): the facade properties (`state`, `notify`, `secrets`, `net`, `schedule`, `fs`, `core`, `hermes_config`, `spawn`) return their facade classes; `ContextServices.audit` is an `AuditSink` and `bridge` a new `BridgePort` Protocol. The audit reader checks the match explicitly. mypy now checks module code against these APIs, which also removed two `type: ignore` comments in `host_t2.py`.

**A-30 · Info**: withheld until #96 is closed.

**A-31 · Info · confirmed-by-reading · errors.py; secrets.py:47-52**
- `SwitchyardError` is the base for usage errors, unknown names, state errors, and "not declared" errors alike. Callers that need to tell "bad input" from "policy refusal" must match strings. A small subclass set (`UsageError`, `PolicyRefused`, `NotAvailable`) would fix this.
- Fixed in 1.1 (#97): `errors.py` adds `UsageError`, `PolicyRefused` (now the base of `CapabilityDenied`) and `NotAvailable` (the base of `SecretUnavailable`, `ApiUnavailable` and the new `ChannelNotFound`). Core raise sites use them; the CLI exits 3 for any policy refusal; the API answers 403 `policy_refused` and 503 `not_available`, and the client raises the same classes. `ops.UsageError` is the same class. `updates.py` no longer matches "not found" in message text.

## Against the prework and the accepted limits

- **Accepted, still holds:** same-user T2 access, model-with-shell, audit anchor in the same directory, and TOCTOU on trust at discovery. A-3 is a different problem (resolution mismatch, not a race), so it is not covered by the TOCTOU acceptance.
- **Accepted, partly holds:** "transformed secret" tripwire. A-7 is a plain value returned through `health()`, which the broker does not reach. That is worse than the documented limit.
- **R1 "torn last line — Fixed":** fixed for the torn case only. A-13 shows an oversized complete last record still makes every append fail, and A-9 shows the torn-tail behaviour still conflates crash and tampering.
- **R1 "two writers forked the chain — Fixed":** confirmed (P18). Four processes, 40 appends each: `exit codes [0,0,0,0] | verify True | records 160`.
- **R1 "facades re-check on every call — Fixed":** confirmed by reading (`_Guarded._check`, context.py:155-157).
- **R1 "module id ending in `_` — Fixed":** confirmed by reading (`_MODULE_ID` in state.py:27 and the schema pattern).

## Things done well

1. Default deny with per-call re-check: `granted()` = store ∩ requested − denied, and unregistered modules get the empty set (capabilities.py:159-165). `_Guarded._check` re-checks on each call (context.py:155-157). Control probe: a denial is `CapabilityDenied` and audited (P2 control).
2. Leak guard works: a result containing the secret → `SecretLeak`, and the use is audited (P22). A failing `fn` surfaces as `secret use failed: ZeroDivisionError` with no `__context__` (P22). Audit records carry no secret values (P16 audit check: False).
3. State confinement: the authorizer denies every escape tried (P17): `sqlite_master`, `kv`, `grants`, PRAGMA, ATTACH, temp DDL, SAVEPOINT, VACUUM, `load_extension`, cross-module prefix, multi-statement. `zeroblob`/`randomblob` size caps hold (state.py:229-247).
4. Work budget: a CPU-bound recursive CTE is stopped at 0.08 s (P06b; state.py:139-160).
5. Audit concurrency: four processes, 160 records, chain verifies (P18). The anchor never moves backwards (core.py:56-65, the `WHERE` clause). Truncation is detected (P5 after append).
6. Manifest checker refuses unknown schema keywords (manifest.py:69-71, `_SUPPORTED`), so the schema cannot rely on keywords the validator ignores. Cross-field rules cover net/secret parity and reserved and `__` ids (manifest.py:114-145).
7. Schema/code drift guard for capabilities: `tests/core/test_policy.py:20` asserts the schema enum equals `CAPABILITIES`.
8. Lifecycle hygiene: trusted-root check on resolved paths (lifecycle.py:202-204), duplicate ids rejected (231-232), failures close the context and report class names only (`_error_name`, 91-94; `_fail`, 333-349), and audit/bus calls are made outside the manager lock (lifecycle.py:324, 349, 378).
9. Event bus gating: `*` and `core.*` subscriptions need `core.read` (context.py:208-214); `emit` restricted to the module's own prefix (context.py:200-206); handler errors are audited by class name (events.py).
10. Host lock uses an OS lock on a dedicated file with non-blocking acquire (hostlock.py:27-49), and the lock is released on close (core.py:287-293). `FileLock` covers the audit's cross-process critical section (hostlock.py:70-119). Both are reasonable Windows choices.

## Not checked

- `net.py`, `updates.py`, `ops.py` (only grep), `bridge.py`, `hermesconfig.py`, `api.py`, `host_t2.py` / `host_t2_child.py` (only grep at the import line), `hostinfo.py`, `fsread.py`, `process.py`.
- Full `events.py` beyond the gating paths (publish, subscribe, matches).
- Migrations SQL (`src/switchyard/migrations/`): grants table keys and constraints.
- `paths.py` junctions inside the data dir (`_make_private_dir` does not refuse reparse points) and the `api.token` ACL.
- Update path (`accept_wider`, rollback) for A-6.
- Test suite, ruff, mypy: not run, because they write caches into the repo.
- Hermes-side wrapping of `health`/`ops` results (untrusted-data labelling and any redaction in the model-tool path).
- Secret backends beyond `MemoryBackend`.
- No network commands were run.

## Probe index

| Probe | Covers | Output |
|---|---|---|
| p01_env_and_policy.py | A-1, A-2 | not saved to a file (printed inline; re-run to reproduce) |
| p02_startup_and_audit.py | A-9, A-10, A-12, A-13 (P9), A-8/A-7 (P7, P8) | not saved to a file (printed inline; re-run to reproduce) |
| p03_manifest_lifecycle.py | A-3, A-4, A-5, A-6, A-17 (P15), A-19 | `out-p03.txt` |
| p04_secrets_state_concurrency.py | A-7 (P16), state confinement (P17), concurrency (P18) | `out-p04.txt` |
| p05_misc.py | A-12 (P19), A-28 (P20), A-18 (P21), leak guard (P22) | `out-p05.txt` |
| p06_cpu.py | A-28 CPU budget | `out-p06b.txt` |

Helper: `_helpers.py` (creates modules and scratch dirs only).
