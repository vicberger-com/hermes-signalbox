# Pre-work Q&A: M1 secrets

Date: 2026-11-19. Previous phase: M0, tag v0.1.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M0 ADR-0001 | Zero runtime dependencies in the core | Applies to bundled modules too unless a dependency passes all five `THIRD-PARTY.md` rules |
| M0 `secrets.py` | Broker with `SecretBackend` protocol (`name`, `available()`, `get(name)`), `use(ref, fn)`, leak check, redactor, audit by name | M1 supplies real backends behind this protocol |
| M0 lifecycle | Brokers are refused to T2 modules; T1 only from the bundled modules directory | M1 ships as a bundled in-process module |
| DESIGN.md section 3 | "Backends are modules (M1); core defines the interface only" | Needs a way for a module to hand a backend to the core broker: a contract change (question 10) |
| M0 security review | The leak check catches the raw value only; T2 is not an OS sandbox | Backends must never return values outside `use()`; `secrets.read` stays a trust decision |
| M0 retro | Credential-shaped fixtures are assembled at runtime; `assert` is not a runtime check | Same rules in M1 tests |

## 2. Research record

| Topic | Source (URL, commit or version, date read) | Finding |
|---|---|---|
| Hermes secret-source API | Hermes v0.23.2 `agent/secret_sources/{base,registry,bitwarden,command}.py`, `hermes_cli/plugins_context.py` (read 2026-11-19) | `register_secret_source(SecretSource)` feeds **env-var-shaped credentials into the Hermes process at startup** (`fetch(cfg, home) -> FetchResult`, must not raise or prompt, wall-clock budget, "mapped" or "bulk" shape). Opposite direction to the broker: it puts values into `os.environ`. `run_secret_cli` shows good practice: minimal allow-listed env, `NO_COLOR`, stdin from null, refs after `--`, ANSI-scrubbed stderr |
| `keyring` library | PyPI keyring 25.7.0, MIT, OSV: 0 advisories (2026-11-19) | Pulls `jaraco.classes`, `jaraco.functools`, `more-itertools`, `pywin32-ctypes` (Windows), `SecretStorage` + `cryptography` + `jeepney` (Linux). Too much supply-chain surface for what is needed |
| OS stores without dependencies | Win32 `CredReadW`/`CredWriteW`/`CredDeleteW`/`CredFree` (advapi32, documented ABI); macOS `/usr/bin/security find-generic-password -w`; libsecret `secret-tool lookup/store/clear` | All three reachable from the standard library: `ctypes` on Windows, fixed-argv subprocess elsewhere. Writing a value through `security add-generic-password -w <value>` would put it on the command line; use `-w` with stdin (`security ... -w` prompts) is not reliable, so macOS **writes** are out of scope for M1 (read only); `secret-tool store` reads the value from stdin |
| Bitwarden / Vaultwarden CLI | bitwarden/clients latest `desktop-v2026.11.0` (2026-11-19); `bw get password <id>` with `BW_SESSION`; `bw status` returns JSON with `status: unauthenticated|locked|unlocked` | Unlock needs the master password, which the operator enters; the module only reads `BW_SESSION` from its configured environment variable and fails closed when `bw status` is not `unlocked` |
| Advisories | OSV for keyring, SecretStorage, jeepney, pywin32-ctypes: 0 open (2026-11-19) | Not used (question 4) |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | What is the smallest scope that meets the acceptance criteria? | (a) four backends + metadata + rotation of generated values + Hermes redaction; (b) also a Hermes `register_secret_source` provider | (a). Backends: `env` (development only, refused unless `allow_env_backend` is set), `wincred` (read/write), `keychain` (macOS, read), `secret-tool` (Linux, read/write), `bw` (Vaultwarden, read). Metadata per name (backend, created, rotated, expires) and `rotate` that writes a fresh random value to a writable backend without ever showing it. (b) is deferred: it copies values into Hermes's environment, which conflicts with "values never leave `use()`"; revisit when a module needs it | default accepted |
| 2 | Which capabilities does the module need, and which can be dropped? | `secrets.read`, `process.spawn`, `ui.panel` | Keep all three. `process.spawn` covers `bw`, `security` and `secret-tool`. No `net.outbound`: `bw` makes its own connections as an external process the operator configured | default accepted |
| 3 | Reuse, adapt or write? | keyring (MIT); Hermes `secret_sources` (MIT) | Write our own. Hermes `run_secret_cli` and `bitwarden.py` are design references (environment allow-list, stdin from null, `--` before refs, ANSI scrub); nothing copied | default accepted |
| 4 | New dependencies? | (a) none; (b) keyring | (a). Rule "smallest trusted base" fails for keyring on Linux (cryptography + 5 more). ctypes and fixed-argv subprocess cover every backend | default accepted |
| 5 | What can go wrong for security? | | See threat table below | default accepted |
| 6 | State schema and migration; what is removed on uninstall? | | Module table `m_secrets__meta(name PRIMARY KEY, backend, created_at, rotated_at, expires_at)` through `ctx.state`; never a value. Uninstall drops it unless `keep_data`. Values in the OS stores are never deleted by uninstall | default accepted |
| 7 | Control surface | | Panel `secrets.status` (names, backend, age, expiry; never values). Module actions (question 10): `status` (read-only), `rotate {name}` (generated values only), `expire {name, date}`. Run through the core operation `module action {id, action, args}` from the CLI, API and `/switchyard`; the Hermes model tool may run only actions the module marks read-only. Config keys under `[modules.secrets]`: `backends` (ordered), `allow_env_backend` (false), `bw_session_env` (default `BW_SESSION`), `rotation_length` (32) | default accepted |
| 8 | Logs, metrics, report section, alerts | | Log stream `secrets` (backend availability changes, rotation, expiry warnings; names only). Expiry within 14 days raises a health detail; alerts are M9 | default accepted |
| 9 | Update source and rollback check | | Bundled; updates with the release. Health check: at least one configured backend available | default accepted |
| 10 | Core contract change (ADR)? | (a) ADR-0002 with two additions; (b) put backends and secret operations in the core | (a). **Secret backends:** manifest `contributes.secret_backends` + `ctx.provide_secret_backend(backend)`, allowed only for in-process modules from trusted roots that request `secrets.read`, so a T2 module can never see every secret. **Module actions:** `ctx.register_action(name, handler, params, read_only)` for names declared in `contributes.commands`, run through one new core operation `module action`; arguments are validated against the declared parameter types, results are JSON-checked and redacted, and the model tool runs read-only actions only. Every later module needs actions, so this belongs in the core contract | default accepted |
| 11 | Operator input needed? | | None to build or test. To use Vaultwarden the operator unlocks `bw` and exports `BW_SESSION` (secret name only) | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Backend value escapes through a result, log, audit, panel or exception | Values only inside `SecretsBroker.use`; backends raise core errors with names only; subprocess stderr is never echoed | `test_canary_never_in_output` across every backend fake and real `wincred` |
| A locked or missing backend silently returns nothing or a wrong value | `available()` checked before `get`; `bw status` must be `unlocked`; missing entries raise `SecretUnavailable` | `test_locked_backend_fails_closed`, `test_bw_status_parsing` |
| Secret on a command line (visible in process lists) | Values are read from stdout and written through stdin or ctypes only; argv carries names only | `test_argv_never_contains_value` |
| Argument injection through a secret name | Names match `[a-z0-9][a-z0-9._-]{0,127}`; refs passed after `--` where supported | `test_bad_names_rejected_before_spawn` |
| Helper CLI hangs or prompts | stdin from null, timeout, minimal environment | `test_helper_timeout_fails_closed` |
| A T2 module registers itself as a backend | `provide_secret_backend` requires in-process + trusted root + `secrets.read` + declared backend name | `test_t2_cannot_provide_backend`, `test_undeclared_backend_refused` |
| Development env backend used in production | Refused unless `allow_env_backend = true`; audited on enable | `test_env_backend_off_by_default` |
| Rotation shows or logs the new value | Value generated with `secrets.token_urlsafe`, written, dropped; audit records name, backend, time | `test_rotate_never_returns_value` |

## 4. Acceptance tests (written before code)

- [ ] A secret value never appears in any tool result, log line, audit record, panel or exception text (canary over every backend).
- [ ] A locked or unavailable backend fails closed with `SecretUnavailable`; the next backend in order is tried only when the first does not have the name.
- [ ] Rotation of a generated secret writes a new value, records `rotated_at`, and is audited by name only.
- [ ] Age and expiry are reported by name in `secrets status` and the panel.
- [ ] Only an in-process module from a trusted root that declares the backend can provide it to the broker.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
