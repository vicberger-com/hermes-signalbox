# Review B: process / network / API boundary, hermes-switchyard v1.0.0

> Published at the close of phase H1 (v1.0.1, 2026-11-20). Every High and Medium finding is fixed; the
> status of each finding is in [findings-index.md](findings-index.md). Findings still open in the 1.1 backlog are
> withheld (`withheld until fixed (#N)`) and are added when their issue closes. Probe scripts are not published.

Scope: `src/switchyard/{api,rpc,host_t2,host_t2_child,process,net,fsread,updates,cli,ops,scheduler,schedule,events,notify,logs,reports,hostinfo}.py`
Method: read-only review of the source, plus probes run against the repo's own code. Probes live in `<workstation>/switchyard-eval/probes/` and used a scratch data dir, loopback only, `python -B`. Nothing was written to `<workstation>/src/hermes-switchyard`. No git, gh or outbound network commands were run.
Docs read first: DESIGN.md §4, ADR-0003, ADR-0010, ADR-0011, m0-core.md, qa/14-r1-prework.md. The accepted limits there (same-user boundary, T2 inherits PATH, leak tripwire, audit anchor in the same directory, no fs.read allow-list) are not re-reported.

## Summary

| ID | Severity | Confidence | Area | Location | Finding |
|---|---|---|---|---|---|
| B-1 | Medium | confirmed-by-probe | updates | updates.py:358-362, 441-461 | A failed swap leaves the module directory missing, or new code installed with no rollback |
| B-2 | Medium | confirmed-by-probe | core lock | core.py:255-258; updates.py:41, 193-195 | Network I/O (git, up to 300 s per call) runs under the one core lock; unrelated reads stall |
| B-3 | Medium | confirmed-by-probe | process | process.py:126-131 | Deadline not enforced while writing stdin; raw BrokenPipeError escapes; no audit record |
| B-4 | Low | confirmed-by-probe | logs | logs.py:59, 64-71 | Long event names make log lines invalid JSON |
| B-5 | Low | - | - | - | withheld until fixed (#98) |
| B-6 | Low | confirmed-by-probe (acceptance); device behaviour suspected | fs.read | fsread.py:38-49, 68-70 | Device-name screen misses superscript aliases (COM¹, LPT³) and trailing-colon names |
| B-7 | Low | - | - | - | withheld until fixed (#100) |
| B-8 | Low | confirmed-by-reading | API client | api.py:301-334; cli.py:119-128 | Stale api.port/api.token trusted; the CLI sends the bearer token to whatever answers |
| B-9 | Low | confirmed-by-reading | CLI/API | api.py:319-322; cli.py:119-128 | Transport error after the request was sent, then offline re-run of the operation (possible double execution) |
| B-10 | Low | - | - | - | withheld until fixed (#103) |
| B-11 | Low | confirmed-by-reading | updates | updates.py:57, 294-299 | Refusal gate for unreviewed files misses compiled extensions (.pyd, .so) and is case-sensitive |
| B-12 | Low | - | - | - | withheld until fixed (#104) |
| B-13 | Low | - | - | - | withheld until fixed (#105) |
| B-14 | Low | confirmed-by-reading | RPC | rpc.py:162-167; host_t2.py:126-148 | Send time is outside the call deadline; a call can run about 2x the documented limit |
| B-15 | Low | - | - | - | withheld until fixed (#106) |
| B-16 | Low | - | - | - | withheld until fixed (#107) |
| B-17 | Low | - | - | - | withheld until fixed (#108) |
| B-18 | Low | - | - | - | withheld until fixed (#109) |
| B-19 | Low | - | - | - | withheld until fixed (#110) |
| B-20 | Info | confirmed-by-probe | API | api.py:162-165 | PUT/PATCH/DELETE/OPTIONS reply 501 without the Host or Origin check |
| B-21 | Info | confirmed-by-reading | scheduler | scheduler.py:140-146 | NaN and inf accepted for `every` and `min_interval_s`; such a trigger never fires |
| B-22 | Info | - | - | - | withheld until fixed (#111) |
| B-23 | Info | - | - | - | withheld until fixed (#112) |
| B-24 | Info | confirmed-by-probe | API | api.py (no handle_error) | Each dropped connection prints a full traceback to stderr |
| B-25 | Info | - | - | - | withheld until fixed (#113) |

Counts: Critical 0, High 0, Medium 3, Low 16, Info 6.

Overall: the loopback API and the frame layer are sound. The Host, Origin, token, size and deadline checks behave as documented under probe. The weak spots are failure paths: the update swap, the lock scope around network calls, and deadlines on stdin writes.

---

## Details

### B-1 (Medium), update swap has no compensating path
- **Location:** `updates.py:358-362` (swap), `updates.py:441-452` (`_restart`), `updates.py:454-461` (`_restore`).
- **What is wrong:** the swap is `deactivate → current.rename(previous) → write sidecar → stage.rename(current)`, with no `try`. Only `_restart` is guarded, and only around `reload`. The `activate` call at line 448 sits outside any `try`, so an exception there propagates out of `update()` without rollback.
- **Evidence:** `updates.py:359 current.rename(previous)` / `updates.py:362 stage.rename(current)` / `updates.py:447-448 ... self._manager.activate(module_id, actor=CORE_ACTOR)`.
  Probe p4 (uses the repo's test helpers and fake fetcher):
  - Scenario A, second rename fails (simulates a Windows directory held open):
    `A: update raised PermissionError: [Errno 13] simulated: directory in use`
    `A: live module dir exists: False`
    `A: rollback audited: False`
  - Scenario B, post-swap activation raises (simulated by replacing `manager.activate`):
    `B: update raised RuntimeError: simulated post-swap failure`
    `B: installed version on disk: version = "0.2.0"`
    `B: installed-ref file: False | rollback audited: False`
- **Impact:** A failed update can delete the live module (A), or leave new code installed while the module is stopped and `installed-ref` still names the old commit (B). Neither recovers without a manual `module rollback`. Scenario A needs an OS-level failure, which is realistic on Windows. Scenario B uses a simulated exception, so its real-world trigger is unconfirmed.
- **Fix:** wrap the swap in `try/except BaseException` that restores `previous → current` (the same logic as `_restore`). Treat any exception from `_restart` as a failed restart. Write `installed-ref` only after success, as now.
- **Suggested test:** monkeypatch `Path.rename` to fail on the second rename and assert the module directory exists and the old version is active. Second test: `manager.activate` raises and assert `module.rolled_back` is audited.

### B-2 (Medium), network I/O runs under the one core lock
- **Location:** `core.py:255-258` (`Core.run` holds `self._lock` around `operation.fn`), `updates.py:41` (`GIT_TIMEOUT_S = 300`), `updates.py:193-195` (git run per call), `updates.py:426-439` (`check_all` loops every module).
- **What is wrong:** `module check_updates`, `preview`, `update` and `rollback` all run `git` (network) inside `Core.run`, which holds the lock for the whole call. `Core.tick` takes the same lock for `manager.tick()`.
- **Evidence:** `core.py:255-258 with self._lock: ... return operation.fn(self, clean, actor)`. Probe p7 (a stub `latest()` sleeps 3 s):
  `check_updates took 3.0s; a read-only 'module list' issued meanwhile waited 2.7s`
- **Impact:** with real git, one hung remote stalls the API, the CLI, the dashboard and idle-stop for up to 300 s per call. `check_all` multiplies that by the number of git modules. This is availability, not confidentiality.
- **Fix:** do the fetch and verify outside the lock (stage without the core lock, then take it only for the swap and the audit write). Use a per-module lock for updates, and a shorter timeout for `ls-remote`.
- **Suggested test:** the probe above, with the stub replaced by a fetcher that blocks, asserting that `module list` completes in under 0.5 s.

### B-3 (Medium), process deadline not enforced while writing stdin
- **Location:** `process.py:126-131`.
- **What is wrong:** `proc.stdin.write(input.encode())` runs before `proc.wait(timeout=...)`, so the timeout does not cover the write. The `input` size is not capped. A `BrokenPipeError` escapes the `except subprocess.TimeoutExpired` handler, which skips `_kill_tree` and `_record`.
- **Evidence:**
  ```
  126: if input is not None and proc.stdin is not None:
  128:     proc.stdin.write(input.encode("utf-8"))
  131: code = proc.wait(timeout=min(max(timeout, 0.1), MAX_TIMEOUT_S))
  ```
  Probe p1, 2 s deadline:
  `control (no input): SwitchyardError: python.exe timed out after 2.9s`
  `case (2MB input, child not reading): BrokenPipeError: [Errno 32] Broken pipe after 15.1s`
  `audit rows: [{'program': 'python.exe', 'result': 'timeout'}]` (the control's row only; the case left no row)
- **Impact:** a helper that never reads stdin blocks the calling thread for as long as the child lives. A module holding `process.spawn` can therefore hang the core, since the call happens under the core lock (B-2). The helper is still killed only by its own exit.
- **Fix:** write stdin on a thread, or use `communicate(timeout=...)`, and apply the same deadline. Cap `input` (for example at 1 MB). Catch `OSError` and call `_kill_tree` and `_record` in every failure path.
- **Suggested test:** the probe above, asserting a `SwitchyardError` within about 2.5 s and an audit record.

### B-4 (Low), long event names make log lines invalid JSON
- **Location:** `logs.py:59` (`event` is not bounded), `logs.py:64-71` (truncation replaces only `fields`, then slices bytes).
- **Evidence:** probe p3: `line 0: 16383 bytes, INVALID (JSONDecodeError)` for a 20 000-character event, and `line 1: ... INVALID` for a 10 000-character multi-byte event. The docs promise a 16 KiB line cap that keeps the header.
- **Impact:** the log stream is corrupt for readers such as `audit tail` or the dashboard, and `{"truncated": true}` does not show. This is a data-integrity issue, not a leak.
- **Fix:** truncate `event`, `module` and `stream` before serialising. Then re-serialise the whole record, or slice on a character boundary, not bytes.
- **Suggested test:** write a 20 kB event and assert every line parses.

### B-5 (Low)

Withheld until #98 is closed.

### B-6 (Low), fs.read device-name screen incomplete
- **Location:** `fsread.py:38-49` (`_RESERVED`), `fsread.py:68-70` (`part.split(".")[0].rstrip(" ").upper() in _RESERVED`).
- **Evidence:** probe p5 (real superscript characters):
  `ACCEPT 'COM¹'`, `ACCEPT 'COM²'`, `ACCEPT 'LPT³'`, `ACCEPT 'LPT¹.txt'`
  Probe p3: `ACCEPT 'C:\\x\\NUL:'`, `ACCEPT 'C:\\x\\CON:'`, `ACCEPT 'C:\\x\\file.txt:hidden'`. `COM1` and `NUL.txt` are refused.
- **Impact:** Windows documents the superscript forms as legacy device aliases. If they resolve to devices, a reader could block on a device or read one. I did not open a device to confirm, because a `stat` on the alias returned FileNotFound in both cases and that test is not conclusive. Alternate data streams are accepted by design (the grant is the decision); they are listed for completeness only.
- **Fix:** normalise each component (strip trailing `.`/space, drop everything after the first `:`) and refuse any component that is a reserved name or has a superscript digit. Add the superscript set. Optionally refuse `:` in path components.
- **Suggested test:** a parametrised test over the names above, asserting refusal.
- Fixed in 1.1 (#99): each component is reduced to the name Windows matches (before any `:` and the first `.`, trailing spaces and dots dropped, superscript digits as digits) before the device-name check. Alternate data streams stay allowed.

### B-7 (Low)

Withheld until #100 is closed.

### B-8 (Low), stale API files trusted; bearer token sent to whatever answers
- **Location:** `api.py:288-292` (files removed only on clean `shutdown`), `api.py:301-307` (`from_data_dir` reads port and token), `api.py:309-334` (`request` sends `Authorization: Bearer` to `127.0.0.1:<port>` and does not check the server's identity).
- **Evidence (reading):** after a crash, `api.port` and `api.token` persist. A process that later binds that port receives the token and can return forged results.
- **Impact:** needs port reuse plus a motivated local process. Another OS user could hold the port, so this is more than the documented same-user boundary, but the attack is narrow. Hence Low, suspected.
- **Fix:** delete stale files at start-up (after checking the PID in a lock file), and bind the CLI to a per-start nonce that the server echoes, or use a named pipe with a user-only ACL.
- **Suggested test:** start the server, kill it without shutdown, bind a fake listener on the same port, assert the CLI refuses or does not send the token.
- Fixed in 1.1 (#101): the client sends a fresh challenge to `GET /v1/health` and sends the token only if the answer is the HMAC of the challenge keyed with the token.

### B-9 (Low), possible double execution of offline operations
- **Location:** `api.py:319-322` (any `OSError` or `TimeoutError` during the request, including after it was sent, becomes `ApiUnavailable`); `cli.py:119-128` (offline operations then run locally).
- **Evidence (reading):** `module grant`, `revoke`, `mode`, `remove` and `audit ack` are `offline=True` (ops.py). A daemon that applied the change and then dropped the connection leads to a second, local run.
- **Impact:** most are idempotent, but `module remove` returns an error on the second run, and an operator sees a failure for a successful change.
- **Fix:** distinguish "connection refused" (safe to fall back) from "sent, no response" (report an unknown outcome, do not re-run).
- **Suggested test:** a fake server that accepts and closes after the body; assert no local re-run.
- Fixed in 1.1 (#102): only a failure to connect falls back to a local run; a failure after the request was sent is `ApiOutcomeUnknown` and nothing runs again.

### B-10 (Low)

Withheld until #103 is closed.

### B-11 (Low), refusal gate for unreviewed files is incomplete
- **Location:** `updates.py:57` (`_UNREVIEWABLE = (".pyc", ".pyo", ".pth")`), `updates.py:294` (`p.suffix in _UNREVIEWABLE`).
- **What is wrong:** compiled extension modules (`.pyd`, `.so`) are not refused, and the suffix test is case-sensitive. Under `-I` the child still imports extension modules from the package directory (`host_t2_child.py:154`). The stated purpose is "not reviewed as source; Python would run them", which `.pyd` and `.so` also satisfy.
- **Impact:** a native library can ship inside an update and pass the gate. The sbom delta lists it as an added file, but it is not flagged as widening.
- **Fix:** refuse `.pyd`, `.so`, `.dylib`, `.dll` and `.pyw`, compare suffixes case-insensitively, and flag any new binary as widening.
- **Suggested test:** stage a tree with a `.pyd` and assert refusal.

### B-12 (Low)

Withheld until #104 is closed.

### B-13 (Low)

Withheld until #105 is closed.

### B-14 (Low), RPC call deadline excludes the send
- **Location:** `rpc.py:162-167` (deadline starts after `_send` at line 164); `host_t2.py:139-146` (send can take up to `self._timeout` before the caller waits). Dispatched replies in the wait loop (`rpc.py:175-177`) also send outside the check.
- **Impact:** the documented "one deadline per call" can be about twice its value. Low, since the child is still killed on timeout.
- **Fix:** compute the deadline before the send and pass the remaining time to the writer.
- **Suggested test:** a child that stops reading and a call with `timeout=1`, asserting completion within about 1.2 s.

### B-15 (Low)

Withheld until #106 is closed.

### B-16 (Low)

Withheld until #107 is closed.

### B-17 (Low)

Withheld until #108 is closed.

### B-18 (Low)

Withheld until #109 is closed.

### B-19 (Low)

Withheld until #110 is closed.

### B-20 (Info), unsupported methods skip Host and Origin checks
- **Location:** `api.py:162-165` (`_unsupported` does not call `_origin_ok`).
- **Evidence:** probe p2, `PUT with evil Host (no Host check on 501 path): (501, ...)`.
- **Impact:** none beyond an information-free 501. Noted because the header says every request is checked.
- **Fix:** call `_origin_ok` first, for consistency.

### B-21 (Info), NaN and inf accepted as trigger thresholds
- **Location:** `scheduler.py:140-146` (`_number` accepts any float; the comparison `<= 0` is False for NaN). `Scheduler.add` then sets `next_due = mono + nan`.
- **Impact:** such a trigger never fires, silently. Not probed.
- **Fix:** require `math.isfinite`.

### B-22 (Info)

Withheld until #111 is closed.

### B-23 (Info)

Withheld until #112 is closed.

### B-24 (Info), socketserver prints tracebacks for dropped connections
- **Location:** `api.py` (no `handle_error` override).
- **Evidence:** probe p2 printed 40 `ConnectionAbortedError` tracebacks to stderr. No request data appeared in them.
- **Fix:** override `handle_error` to log the class name only.

### B-25 (Info)

Withheld until #113 is closed.

## Done well

- **API request checks.** `api.py:152-160` (Host must be `127.0.0.1:<port>` or `localhost:<port>`; any Origin refused), `api.py:180` (`hmac.compare_digest`), `api.py:194-196` (size checked before read), `api.py:183-185` (JSON content type). Probe p2: DNS-rebinding Host 403, `Origin: null` 403, no token 401, text/plain 415, 70 000 bytes 413, query string 404, good request 200.
- **Token and headers.** `api.py:257` (`secrets.token_urlsafe(32)`), `api.py:51-54` (`safe_header` rejects CR/LF), `api.py:104-105` (request lines never logged), `api.py:113-121` (`nosniff`, `no-store`).
- **Frame layer.** `rpc.py:88-89` (size checked before the body is read; probe: `frame too large (2000000 bytes ...) | body consumed: False`), `rpc.py:178-179` (response id must match), `rpc.py:164-172` (one deadline per call; probe stopped at `0.50s`), `rpc.py:56` (`allow_nan=False`; probe rejected NaN).
- **Child environment and kill-on-timeout.** `host_t2.py:53-56` (environment allow-list; probe: the planted secret was absent from the child env), `host_t2.py:91-100` (fixed argv, no shell), `host_t2.py:107-124` (flood handling), `host_t2.py:139-148` (send deadline). Probe p8: a hanging `activate` raised `T2Timeout after 2.2s` and the child exited.
- **Network broker.** `net.py:43-45` and `net.py:65` (no redirects, no env proxies), `net.py:94-97` (scheme, credentials and host checks), `policy/capabilities.py:182-194` (exact or bare host). Probe p6: a 302 was returned, not followed (second server 0 hits); `localhost`, `127.0.0.1`, `[::1]`, `0.0.0.0`, decimal IP, `file:` and credentialed URLs were all refused.
- **fs.read path syntax.** `fsread.py:56-74` (drive letter required; UNC, `\\?\` and drive-relative paths refused, probe-confirmed), `fsread.py:120-125` (`fstat` on the open handle), `fsread.py:130-132` (bounded read), audit records path and byte count, never content.
- **Update pipeline.** `updates.py:157-159` (ref must be 40 lower-case hex), `updates.py:188-190` (`GIT_CEILING_DIRECTORIES`, `core.hooksPath` to null, `protocol.file.allow=never`), `updates.py:215` (`HEAD == ref`), `updates.py:291-299` (symlinks refused), `updates.py:340-347` (digest-bound update, widening gate). Manifest `version` regex excludes `/` and `\`, so the `previous-<version>` directory name cannot traverse (`manifest`/`module.schema.json`).
- **Event bus and notifications.** `events.py:166-178` (each handler gets a copy; exceptions audited by class name only), `events.py:33,106` (size caps), `notify.py:46-51` (redact before truncating, as the comment says).
- **Operation boundary.** `ops.py:31-45` (`MODEL_OPS` allow-list), `core.py:251-253` (enforced in `Core.run`), `api.py:236-241` (dashboard profile limited to named operations).
- **Tooling.** `mypy --strict` passes on the 17 in-scope modules (Success: no issues found in 17 source files). `ruff check` passes. `bandit -ll` printed no findings, only configuration warnings. No `shell=True`, `eval`, `exec`, `pickle` or bare `except:` in scope (grep).

## Not checked

- Real `git` against a remote (fetch, ls-remote, the 300 s behaviour). B-2 uses a stub fetcher.
- An item for withheld finding B-22.
- Windows device I/O for the superscript and colon names (B-6). I did not open a device.
- An item for withheld finding B-17.
- The full pytest suite. I did not run it, to keep the repo free of cache and coverage writes.
- Concurrency under a live daemon: two processes on one data dir, and the CLI-to-daemon fallback (B-9) under real load.
- Hermes adapter (`hermes/`), dashboard panel and inbox modules: outside this scope.
- An item for withheld finding B-15.

## Issues encountered

- `.coverage` (modified 10:21) and `.git/FETCH_HEAD` (10:17) changed during this session. I ran no git and no pytest, and none of my probes write `.coverage`, so another process touched them. I did not investigate. Flagging for the operator.
- Two probe scripts had a mistake in their first run (a raw-string superscript test and a wrong entry-class name). I fixed and re-ran them; the results above are from the corrected runs.

## Probe index (scratch)

| File | Covers |
|---|---|
| p1_process.py | B-3 deadline and stdin |
| p2_api.py | API request checks, B-20; one withheld finding |
| p3_misc.py | B-4, RPC framing and deadline; one withheld finding |
| p4_update.py | B-1 swap scenarios |
| p5_fsnames.py | B-6 device names |
| p6_net.py | net redirects and allow-list |
| p7_lock.py | B-2 lock |
| p8_t2.py | T2 environment and deadline |
