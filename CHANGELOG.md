# Changelog

Format: Keep a Changelog. Versions: Semantic Versioning.

## [Unreleased]

### Changed (breaking)

- **Renamed from Switchyard to Signalbox** (ADR-0015, [UPGRADING-1.1.md](docs/UPGRADING-1.1.md)): plugin, chat
  and CLI command `signalbox`, standalone command `hermes-signalbox`, model tools `signalbox_*`, import package
  `hermes_signalbox` (`SignalboxError`), distribution and repository `hermes-signalbox`, dashboard tab
  `/signalbox`. The old names are not kept: update scripts, saved prompts and service definitions.
- On first start, a Switchyard 1.0.x data directory in the default location is copied (never moved) to the new
  one, after its audit chain verifies; `core.migrated` is recorded and the old directory is left for rollback.
  Refused, with nothing written, while a 1.0.x process still holds it.

### Added

- **Plain-language labels** (#205, #208): one table, `hermes_signalbox.labels`, with a label and a one-sentence
  meaning for every capability, module status, start mode, alert severity, actor and core audit action. A test
  fails when one is missing.
- **Report summaries** (#207): every `report show` result now carries `purpose` (the question the report
  answers) and `summary` (`headline`, `counts`, `lines`), computed from the report data alone.
- **Module details** (#210): `module show` reports `source` (bundled, or the git repository, installed commit
  and channel), `links`, `based_on` and `update` (the last known update state; it never contacts the
  network). The dashboard's module rows carry the same details plus each module's description and its state
  in plain words.
- **Optional manifest links** (#210): `[module] homepage`, `docs` and `based_on = [{name, url, license}]`.
  Plain `https://` URLs only; a manifest with any other link (http, `javascript:`, credentials, spaces,
  quotes) fails to load.
- **Command-line tables fit the terminal.** When a table is wider than the window (`module list` on a normal
  terminal), each row is written as a block: the name, then `Column: value` lines wrapped to the width. Wide
  windows and `--json` are unchanged.
- **The chat command accepts command-line style arguments.** `/signalbox report show --kind health`,
  `--kind=health` and `kind=health` now mean the same, and `--json` works like `json=true`. A flag without
  its value gets a message saying what is missing instead of `expected key=value`.
- **Documentation for the new output and dashboard** (#205-#208, #210): the user guide describes each
  dashboard view and what the page cannot do (section 5), how to read chat and command-line output and get
  the raw data, and a glossary of every label generated from the program's label table (section 12,
  `tools/gen_glossary.py`). REFERENCE lists the dashboard routes. Install commands in QUICKSTART and
  TROUBLESHOOTING name the repository `vicberger-com/hermes-signalbox`. Every bundled module's manifest has
  a `docs` link, shown in the Modules view.
- **The dashboard's Reports and Inbox views are readable** (#207, #208). A report opens with its one-line
  summary and what it is for, then a table (module health, refusals grouped with a count, changes as
  sentences) with local times; the stored JSON is one click away under "Raw data" and is no longer cut off
  in a scroll box. The Inbox shows when each notice arrived, how serious it is (icon, word and meaning),
  labelled details, repeats merged with a count, an Open / Acknowledged / All filter and the open count on
  its tab; a failed acknowledge is shown. Refresh is a separate button that says "Refreshing" while it
  works and shows when the page was last updated, and the page has a "What is this page?" introduction.
- **Report and Inbox data for the dashboard** (#207, #208): the dashboard backend's `GET /report/{kind}` adds
  `view` (a timeline of sentences for changes, grouped and labelled refusals for security, module rows with
  failures first for health, readable lines per source for usage), and `GET /inbox` adds `groups` (identical
  notices merged with a count, severity and detail fields labelled) and `open`. The stored report and items
  are returned unchanged next to them. The views that use this follow in the next change.
- **Label glossary for the dashboard** (#208): `GET /labels` in the dashboard backend serves the label tables.
  It is static and makes no call to the core.
- **Start-up notice for modules waiting for permissions** (#221): a module set to start with Hermes that is
  missing a permission used to be skipped with only an audit record. The hosting process now says so once per
  start: a warning in the Hermes log (logger `signalbox`), or on stderr for `hermes-signalbox serve`, naming
  each module, what it needs and the command that grants it. `module.auto_skipped` is still recorded.

### Changed

- **The dashboard API can set a module's start mode** (#206): `POST /modules/{id}/mode` in the dashboard
  backend, behind the same write guard as activate and deactivate, audited as `module.mode_changed` with actor
  `api`. The restricted API profile Hermes runs now accepts `module mode`; grants, installs, updates, removal
  and config are still refused there. The Modules view gets the control in the next change.
- **The dashboard's Modules view explains itself** (#206, #208, #210). Each row shows what the module does,
  its state in plain words, version, source (with links to the repository, homepage and documentation) and
  update state. The start mode is a selector. A module that cannot start has a disabled button with the
  reason and the exact grant command; a refused action shows the core's message on its row instead of
  doing nothing. Status and mode have tooltips that open on hover and on keyboard focus and close with
  Esc, and a legend sits under the table. Only plain `https://` links are rendered, with the host shown
  and `rel="noopener noreferrer"`.
- **Chat replies are readable** (#205): `/signalbox <noun> <verb>` answers in Markdown, with a summary line,
  a table with each module's description and state in plain words, and the next step (for example the grant
  command). Add `json=true` for the previous JSON reply, unchanged.
- **CLI text output uses the same formatter** (#205): `module list` prints a summary and a table instead of
  `key=value` rows; `module health` prints a sentence. **Scripts that parse the text output must switch to
  `--json`**, which is unchanged. The model tools are unchanged too.
- A module action argument named `json` can no longer be passed from the chat command, because `json=` now
  selects the reply format; pass it from the CLI (`--args`) instead.

### Deprecated

- `SWITCHYARD_DATA_DIR` and `SWITCHYARD_SECRET_<NAME>` are still read in 1.1.x with a warning; rename them to
  `SIGNALBOX_...`. Secrets stored under the old keychain service or credential prefix are still read when the new
  name has none. All three are removed in 1.2.0.

### Removed

- Stray build artifacts `bandit-report.json` and `pr_body.md` from the repository root.

### Fixed

- **Modules view fits an ordinary display** (usability review of the release candidate): at 1366 pixels wide the eight-column table showed three modules of twelve, because Source and Update said the same on every row and made every other cell wrap. The table now has five columns (Module, State, Start mode, Version, Action). Source, update state, how the module runs, its permissions, licence and links are behind one **About** control beside the name, which opens on hover, keyboard focus and click; "From git", "Update available" and "Update check failed" stay visible beside the name. State says whether the module runs (Running, Not running, Needs permissions, Error) and no longer repeats the start mode; a health problem shows under it. A summary line counts the modules, the view tabs look like tabs, and notes use the dashboard theme's colours. The page no longer stretches across a wide display: tables take the width of their content, the page stops growing at a readable width and shrinks below it. "What the columns mean" is folded away under the table like the page introduction.
- **`--json` works at the end of a command** (usability review of the release candidate): the text output
  ends with "Raw data: add --json.", and `module list --json` was refused; the flag was only accepted before
  the noun. It is accepted in both places. Usage and error text now name the command that was typed
  (`hermes signalbox`, not `hermes-signalbox`, when run through Hermes).
- UPGRADING: added the step that changes `delegation.backend` in the Hermes configuration.
- **An option given twice is refused** (repository review D-1): `module grant <id> --capability a --capability b`
  kept the last value and dropped the first without a word, at the terminal and in chat, so a pasted grant
  line gave one permission out of several. It now stops with "was given more than once; run one command for
  each value". Grant one permission per command.
- **Quick start and troubleshooting pages corrected** (D-2): the quick start granted only `ui.panel` to each
  module (see above) and appended a line to `config.toml` that is not valid TOML; the troubleshooting page
  showed commands that do not exist (`module run`, `secrets add <name> <value>`, `audit tail -n`, a bare
  `signalbox` command) and told the reader to start a second daemon beside Hermes. Every command on both
  pages is now parsed by a test, and the quick start's grant list is checked against the bundled manifests.
- ROADMAP no longer lists subprocess isolation as future work; CONTRIBUTING explains the commit title prefix.

### Security

- **Independent re-review of 1.1.0** (2026-11-27, three reviewers with no part in writing the code; record in
  [docs/qa/19-h5-prework.md](docs/qa/19-h5-prework.md) section 9). The first review (below) was a
  self-review, and its fix for module-written text was incomplete. Each finding was reproduced before it
  was fixed:
  - **R-4** Module-written text could still shape a chat reply: `_word_` and `~~word~~`, text that starts a
    line as a list, heading or code block, and bare web addresses that became links. All are now shown as
    the words they are. A module's declared links are therefore plain text in chat; the dashboard shows
    them as links, with the host visible.
  - **R-5** A deeply nested result raised `RecursionError` in the formatter. It is cut off at 32 levels.
  - **R-6** The failure line on stderr (`module health`, `module activate`) carried module-written text,
    escape sequences included. A subprocess module could choose the error type name shown for it.
  - **R-7** First-start copy of a 1.0.x data directory: an old directory that is itself a link was followed;
    the copy ran again whenever the new state was missing, which brought back grants revoked since; a
    damaged `state.db` was copied unchecked; an operating-system error escaped as a traceback; copied files
    kept their permission bits (POSIX). The copy now happens once: a file `migrated-to-signalbox.txt` is
    written into the old directory, and a directory that carries it is not copied again.
  - **R-8** `--data-dir` and `api serve --port` given twice kept the last value silently.
  - **R-9** The dashboard received module-written text with control and direction-override characters.
  - **R-10** A module could post an inbox notice that named another module as its source.
  - **R-11** The dashboard's start-mode route read a body of any size and content type; a list where a
    module id belongs dropped the connection.
  - Known and not fixed here (SECURITY.md, "Known limits"): the Hermes dashboard gives its session token to
    any program on this computer that asks, so another local program or account can start and stop modules
    and change start modes through it (never grant, install, update or remove); a 1.0.x data directory is
    imported whole, with its `config.toml` and `modules/`.
- **Phase-end review of 1.1.0** ([record](docs/qa/19-h5-prework.md), section 8). Fixed before release:
  - R-1: the new chat and terminal formats printed text written by modules (health detail, action output,
    notices, audit detail, manifest descriptions) as it came. In a chat reply it is now shown as plain words:
    line breaks become ` / ` and the characters that start a Markdown link, image, tag, code span, heading,
    quote or emphasis are escaped. Both formats drop control and direction-override characters, so a module
    cannot send terminal escape sequences. `json=true` and `--json` return the payload unchanged.
  - R-2: the formatter raised on a list result that did not hold records; it now shows it as a plain list.
  - R-3: the first-start copy of a 1.0.x data directory followed links. A directory that contains a symbolic
    link or a Windows junction is now refused with the link named, and nothing is copied.

### Process

- **Trust but validate** ([ADR-0016](docs/adr/0016-trust-but-validate.md), operator statement of 2026-11-27): for
  every function the operator can see whether it is safe, whether it was done, whether it was done right
  and what should improve, and can correct it. Pre-work question 13 and a validation gate apply from the
  next phase. The [gap analysis](docs/qa/20-validation-gap.md) records where 1.1.0 does not meet it: no
  per-module screen, status panels registered and not displayed, module settings in effect not shown.
  H6 (v1.2.0) builds the per-module screens.
- Pre-work Q&A question 12 (audience and presentation) and two gates: presentation, and an operator usability
  review before a release counts as accepted. From v1.0.3 user testing (#205, #206, #207).

## [1.0.3] - 2026-11-24

Maintenance release from phase H4: fixes every finding of the first install acceptance of v1.0.2 on a real
Hermes Desktop baseline ([Q&A](docs/qa/18-h4-prework.md), [ADR-0014](docs/adr/0014-hermes-hosting-process.md)).

### Upgrading from 1.0.2

- Install by owner/repository and commit (`hermes plugins install vicberger-com/hermes-switchyard --force --ref
  <SHA>`), never by the catalog name `hermes-switchyard`, which is an unrelated project.
- Restart Hermes once after the upgrade (`hermes gateway restart`) so the gateway hosts the modules under the new
  hosting rule; `hermes -p <profile> switchyard config show` then prints `hosting.pid` = the gateway's pid.
- Delete `plugin-data/switchyard` in the Hermes home if 1.0.2's dashboard tab created it; it is unused.
- Remove a module while Hermes runs with `/switchyard module remove <id>` in a chat; the command line refuses
  while another process hosts.
- Uninstall: `hermes plugins disable switchyard`, then `hermes plugins remove switchyard` (user guide section 9).
- Scripts: `module grant` to an unknown module exits 2 (was 3); read `ok` and `detail` from `module health`
  rather than comparing the whole result (it now carries `host_pid`).

### Fixed

- R1-F8 (High): inside Hermes, only the gateway (or, without one, a process that runs turns) hosts the modules.
  A one-shot command such as `hermes gateway status`, `hermes gateway restart` or `hermes switchyard ...` no
  longer becomes the host for its lifetime, which left the gateway running turns without hooks, gates and
  transforms. A process that may host and finds the data directory taken retries every 5 seconds and records
  `core.hosting_acquired` when it takes over ([ADR-0014](docs/adr/0014-hermes-hosting-process.md)).

- R1-F14 (Medium): when Hermes unloads the plugin in a running process (disable, uninstall, forced reload),
  Switchyard now stops there: modules are deactivated (`module.deactivated` with reason `unload`), the loopback
  API stops and `api.port` / `api.token` are removed, and the host lock is released. Before, all of it stayed
  alive in the gateway until the gateway was restarted. A stop step that fails no longer keeps the host lock.

- R1-F9 (Medium): `module mode` from the command line now reaches the process that hosts the modules. The host
  reads a module's mode from the state store before it acts on it (activation, `auto` start, the model's
  `auto`-only rule, `module show`), and its tick stops a running module another process set to `disabled`
  (`module.deactivated` reason `disabled`). Before, the host kept the mode it read at load, ignored the change
  and wrote its old mode back on the next activation. Each write to the `modules` table now touches only its
  own columns, so a command-line call no longer resets the `state` column of modules the host runs, and a
  process that starts hosting writes the true state of every module.

- R1-F10 (High): the dashboard tab now reaches the plugin's loopback API. Its backend looked for the API in
  `plugin-data/switchyard` (and created that directory), while the plugin keeps its data in the directory Hermes
  gives it (`plugin-data/agent-plugin-switchyard-<digest>`), so the tab said "API is off" although it was on. The
  backend now resolves the directory with the plugin's own rule (the plugin's `data_dir` setting, then
  `SWITCHYARD_DATA_DIR`, then Hermes's plugin data directory) and creates nothing. A `plugin-data/switchyard`
  directory left by v1.0.2 is unused and can be deleted.
- R1-F11 (Low): the dashboard's Health column is filled: `ok`, `failing: <detail>`, or `unknown` for each running
  module, empty for modules that are not running.

- H4-N1 (Medium, found while fixing R1-F9): `module revoke` from the command line now stops the module in the
  process that hosts it. Before, while Hermes hosted, a module that needed the revoked capability kept running
  there, with the hooks, gates and jobs it had registered under the grant, until Hermes restarted. The host's
  tick now stops an active module whose required grants are incomplete (`module.deactivated` reason
  `revoked <capability>`), within 15 s in Hermes and 1 s for the daemon. Optional capabilities are still
  checked when used.

- R1-F5 (Low): a live command (`module activate`, `health`, `panel`, ...) run while another process, usually the
  Hermes gateway, hosts the data directory with the API off no longer says to start `switchyard api serve`, which
  cannot start there. It names the steps that work: `/switchyard <command>` in a Hermes chat, or
  `[api] enabled = true` in the data directory's `config.toml` and a Hermes restart.
- R1-F7 (Low): setting the mode a module already has no longer records `module.mode_changed`.
- R1-F12 (Low): the usage report says why a module's section is missing (`unavailable: not installed`,
  `not active` or `action failed`) instead of printing an exception class name such as `UsageError`.

### Changed

- `config show` prints `hosting.here` and `hosting.pid`; `module show` and `module health` carry `host_pid`
  (the process that hosts the data directory, `None` when nobody does). Scripts that compared the whole
  `module health` result must read `ok` and `detail`.
- New audit action `core.hosting_acquired` (one record each time a Hermes process starts hosting).
- `module remove` from the command line is refused (exit 1) while another process hosts the data directory,
  naming that process: the host would keep running the module on grants and data the command just dropped.
  Remove it where it runs (`/switchyard module remove <id>` in a Hermes chat), or stop that process first.
  With `switchyard api serve` the command goes through the daemon as before.
- R1-F4 (Low): `module grant` to an unknown module exits 2 (usage error), as the exit-code table in
  `docs/REFERENCE.md` says for an unknown name; it exited 3 (denied). The API answers 400 instead of 403, and
  the model sees `UsageError` instead of `CapabilityDenied`. The attempt is still audited as
  `policy.grant_refused` (reason `module not registered`). Scripts that treated exit 3 as "unknown module" must
  check for 2.

### Documentation

- R1-F1, R1-F2: README and user guide section 1 say to install by owner/repository and commit only: the Hermes
  catalog's `hermes-switchyard` entry is an unrelated project. The install's "custom (unreviewed) source"
  warning is expected.
- R1-F3: section 4 says the model tools reach new chats only after `hermes plugins enable`.
- R1-F6: section 3 says a grant never starts a module in a running Hermes, and how to start it.
- R1-F13: sections 6 and 7 mark reports and update commands as chat-only (`/switchyard ...`) while Hermes hosts.
- doc-1: section 9 disables the plugin before removing it, says what Hermes's reply means and when to restart
  the gateway, and names every data directory to delete; the stray second section 5 is now section 11. The
  workstation deployment page in the wiki matches.


## [1.0.2] - 2026-11-24

Maintenance release from phase H3: audit noise reduction, process hardening, API configurability, T2 shutdown detail, error semantics, Unix device path refusal, and security documentation (findings H3-16 through H3-27; H2 regressions H2-2, H2-3, H2-4 addressed).

### Fixed
- T2 child process no longer emits `module.verified` audit on start (H3-16, H3-18, H3-21). Parent process already wrote it during discovery.
- `resources.resolve` audit window extended to 5 minutes (H3-17). Reduces per-call overhead from ~21 ms to one record per 5 minutes per caller/action.
- Process-start `module.verified` audit deduplicated via manifest fingerprint; unchanged modules announced only on in-process event bus (H3-21).
- `system_program()` used for all Windows system tools (`taskkill`, `icacls`) ensuring they resolve from `%SystemRoot%\System32` even when Task Scheduler starts in System32 (H3-19).
- Unix environment variable hardening expanded: blocks `LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_INSERT_LIBRARIES`, `DYLD_LIBRARY_PATH`, `PYTHONPATH`, `PYTHONHOME`, `JAVA_TOOL_OPTIONS`, `SSH_AUTH_SOCK`, `GPG_AGENT_INFO`, `GPG_TTY`, `PINENTRY_USER_DATA`, and prefixes `LD_`, `DYLD_`, `PYTHON`, `SSH_`, `GPG_`, `PINENTRY_` plus suffixes `_PATH`, `_LIBRARY_PATH` (H3-24).
- API server `max_connections` and `request_read_deadline_s` now configurable via `config.toml` under `[api]` (H3-20). Defaults unchanged (16, 10s).
- T2 `shutdown_error` records full exception detail (`"{type}: {message}"`) instead of just class name (H3-22).
- New error classes `ModuleNotRunning` and `BrokerUnavailableToSubprocess` (subclasses of `NotAvailable`) for clearer semantics (H3-23). `NotAvailable` retained for backward compatibility.
- `fs.read` refuses Unix device paths `/dev/`, `/sys/`, `/proc/` (H3-25). Parity with Windows device alias refusal.
- USER-GUIDE security notes added: challenge context versioning (H3-26) and Unix env var hardening (H3-27).

### Documentation
- `docs/qa/16-h3-eval-prework.md`: H3 evaluation findings (15 from real-install, 12 from security review).
- `docs/qa/17-h3-prework.md`: H3 pre-work Q&A with retro (section 7).
- USER-GUIDE section 5: security notes for future-proofing.

### Testing
- All tests pass (995 tests, 94.72% coverage).
- ruff, mypy strict, bandit (0 findings), pip-audit clean.
- CI: Windows/macOS/Ubuntu x Python 3.11-3.14, hermes-integration job (real Hermes v0.23.2, meter exact).

### Upgrading from 1.0.1
- No breaking changes. Configurable API limits use safe defaults.
- New error classes are subclasses of `NotAvailable`; existing `except NotAvailable` handlers still catch them.
- Unix env var hardening only affects spawned subprocesses; no impact on in-process modules.

## [1.0.1] - 2026-11-20

Maintenance release from phase H1: fixes for the 2026-11-20 evaluation of v1.0.0 (every High and Medium
finding; index in `docs/qa/h1/findings-index.md`).

### Upgrading from 1.0.0
- `module activate` refuses (exit 3, `policy.denied` audited) until every required capability is granted;
  grant them first (`switchyard module show <id>` lists them under `missing_grants`). The model may start only modules in `auto` mode.
- A delegated persona model with no registered cost is treated as paid: register its cost to keep it free.
- An explicit `--data-dir` (or the plugin's configured directory) now wins over `SWITCHYARD_DATA_DIR`.
- Modules from outside the bundled roots must run as subprocess (T2) modules; in-process is bundled-only.
- A grant whose capability a module's manifest no longer requests is removed (audited `policy.revoked`).
- A module whose hooks time out 3 times is paused for 60 seconds (`module.hooks_paused`); an expired
  activation preset ends at the next turn.

### Fixed
- Release workflow: the annotated-tag check fetches the pushed tag object first (`actions/checkout`
  rewrites a pushed tag as a lightweight ref, so the check refused every tag). The first `v1.0.1` tag's run
  stopped there and published nothing; the tag was re-created on the fixed commit.

### Security
- Module updates: the swap step re-checks, under the core lock, that the installed module is still the one
  that was staged and compared; otherwise the update is refused and audited (phase-close review CR-1).
- Release workflow (H1 D-3): a `verify` job re-runs the full gate and checks that the tag is an annotated tag on
  `main` matching the project version; the release job needs it. Release notes come from this file.
- Router: H1 C-1, C-4, C-8 (ADR-0013). A route that misses the bridge deadline fails closed: a remembered
  free candidate is sent, or a paid configured model is charged as a paid pass-through; late route results
  never charge or record. Cool-downs are never shortened by a later error. Every request shape is sized.

### Changed
- Real-Hermes integration test (H1 D-4). CI job `hermes-integration` installs Hermes Agent v0.23.2 (commit
  `ae2a81c`, the release the operator runs) from a checkout with `uv sync --frozen`, then loads Switchyard
  through Hermes's own plugin discovery and drives the model tools, the slash command, hooks, `llm_request`
  middleware and the dashboard API module through Hermes. The job never skips and is required by `ci-required`.
- Project status is **Beta** (`Development Status :: 4 - Beta`; H1 D-14). SECURITY.md states the support and
  deprecation policy: breaking changes only in minor releases, with the operator step in this file.
- Documentation and metadata (H1 WP10). The dashboard manifest version matches the package, and a test checks
  every version field (D-17). Pre-commit hooks are pinned to the same ruff and gitleaks versions as CI (D-16).
  REFERENCE.md no longer claims to be generated; it documents `--json`, `--data-dir`, `backup/`, the
  `trigger.*` and `module.*` events and the module states and modes, and a test checks every operation is
  listed (D-19). `docs_gap_audit.md` moved to `docs/qa/` as a historical record (D-18). DESIGN section 6 lists
  only the Hermes mechanisms the plugin uses. Docs corrected: `policy.denied` is an audit record, not an event
  (A-26); CTEs are allowed and bounded by the work budget (A-28); the resources module's `import_preview` is
  operator-only (C-11). Shared module helpers (`switchyard.modkit`) replace seven copies of the state helpers
  and four of the integer-setting check (C-13).
- Audit log and startup (H1 WP9). A torn last line (a crash mid-write) is repaired when the log is opened, so
  startup no longer reports it as tampering; a record whose final newline was stripped now fails `verify` (A-9).
  `audit tail` splits on `\n` only, so records holding U+2028/U+2029 read back (A-8). A failed start releases the
  host lock and closes the database (A-10). `audit ack` records the acknowledgement before clearing the warning
  (A-11). Policy denials with long module-supplied values are always recorded, values shortened (A-2). Bad bytes
  or deeply nested JSON in the log give a verify report instead of an exception (A-12); records are capped at
  128 KiB and the last record is found whatever its size (A-13); short writes are completed (A-14). Log lines
  with long event names stay valid JSON (B-4).
- Hot path (H1 WP8). Bridge calls have a per-module circuit breaker: three timeouts in a row pause that module's
  hooks, gates and middleware for 60 s (audited `module.hooks_paused`), and at most 4 calls per module run at once;
  observers run side by side against one shared deadline (C-2). The core's own scan of tool output has a 0.5 s
  budget per step; past it the output is kept unchanged and `core.transform_skipped` is audited (C-3). Observers
  of `post_api_request` and `api_request_error` get `sent_model`, the model the request actually went out with,
  and the meter charges that model (C-5). Adapter errors are audited once as `core.adapter_error` and the gate
  still runs when observers fail (C-9). Float token counts are rounded, not dropped (C-10). The activation
  module's health check no longer ends an expired preset; that happens at the next turn (C-16).
- Failure paths (H1 WP7). A failed directory swap during `module update` puts the previous version back and
  audits `module.rolled_back`; any error while restarting the new version counts as a failed restart (B-1).
  `module update`, `preview` and `check_updates` run git without the core lock; only the swap takes it, and one
  update per module runs at a time; `ls-remote` times out after 60 s (B-2). The process broker's deadline covers
  writing stdin, input is capped at 1 MB, and every failure path kills the tree and is audited (B-3). Updates
  also refuse `.pyd`, `.so`, `.dylib`, `.dll` and `.pyw` files, case-insensitively (B-11). An RPC call's deadline
  includes the send (B-14). Trigger numbers must be finite (B-21). The T2 flood kill and stalled-writer kill now
  run in the suite (D-11).
- Core trust (H1 WP6). An explicit `--data-dir` / `Core(data_dir=...)` now wins over `SWITCHYARD_DATA_DIR` (A-1),
  and the module contract no longer reads it. An entry `X.py` beside a directory `X/` is rejected, and module code
  is checked after import to come from inside its directory (A-3). `run_contract` has a `trust` check: in-process
  modules outside the bundled modules fail unless `bundled=True` (A-4). A stored grant the manifest no longer
  requests is removed (`policy.revoked`, reason `no longer requested`) and must be granted again if a later
  version asks (A-6). Operation results (health detail, panels, actions) pass through the secret redactor (A-7).
  Backend errors reach callers as their class name only, audited as `secret.backend_error` (A-18). The manifest
  validator checks the `policies` grammar (A-19). Smaller: A-15, A-21, A-22; `bw` drops one trailing newline (C-15).
  **Operator step:** a third-party in-process module must move to `isolation = "subprocess"` to pass the contract.
- Activation (H1 A-5, C-6, decision D8): a module starts only when every required capability is granted;
  otherwise activation is refused (`policy.denied`, exit 3 in the CLI) before any module code runs, and the
  module is not marked failed. The model may start only modules in `auto` mode. **Operator step:** grant every
  required capability before `module activate` (`module show <id>` lists `missing_grants`), and set modules
  the model should be able to start to `--mode auto`.
- Router (H1 C-7): for delegated subagents, a model the registry does not know is treated as paid (steered to
  a free resource, or counted as a paid pass-through). **Operator step:** register persona models with their
  real cost class.
- Packaging (H1 D-5, D-6, D-25): the wheel ships `py.typed`, `plugin.yaml` and the dashboard files (under
  `switchyard/_plugin/`); CI builds the wheel and sdist, checks the wheel's file list against
  `tools/wheel_files.txt` and smoke-tests a clean install; the release SBOM lists what the wheel installs, not
  the build tools; `[build-system]` pins `hatchling>=1.27,<2`. A pip install has no dashboard tab in Hermes
  0.23 (use `hermes plugins install` for it).
- CI (H1 D-12, D-23): Python 3.11 to 3.14; the skipped tests must match `tests/skip_allowlist.json` per OS.
- Updates (H1 D-2, D-15): git is the first runnable git on `PATH` (Windows hosts with Hermes Desktop put a
  packaged git first that other processes may not run), or `[tools] git` when set; `config show` prints the
  git in use. Programs found in the working directory stay refused, now tested on every OS.
- Bridge: `ctx.hermes_middleware` takes an optional `fallback`; middleware gets `context["claim"]`
  (ADR-0013). State store: `ModuleState.deadline(seconds)` bounds a thread's store waits.
- Router: a request with no recognised text key is sized as tier T5. With `hard_stop = true` the turn after
  a slow route that let a paid model through is blocked once (`route timeout`). No operator step needed.
- CLI (H1 D-7, D-8, D-9, D-10, D-26): a result with `status: failed` or `ok: false` exits 1 and says why
  (missing grants are named); an unknown capability name exits 2; `module panel` on an inactive module says
  so; `config show` prints `data_dir_source` and nested settings as `section.key: value`; `--help` marks
  operations that need the daemon with `[daemon]`. Scripts that relied on exit 0 for failed results must
  check the new exit code.
- Daemon: SIGTERM and Ctrl+Break stop `switchyard api serve` cleanly; the readiness line is flushed. The client
  removes `api.port`/`api.token` left by a daemon that died (only while no process holds `host.lock`) and
  connects with a 0.5 s timeout.
- `module list` / `module show` add `missing_grants`. The model tool description no longer names
  `deactivate` (H1 D-20).
- Loopback API: unsupported methods are Host/Origin-checked too; dropped connections print no traceback
  (H1 B-20, B-24).
- User guide: two data stores explained, `switchyard api serve` as step 0, the capabilities each module needs
  to start, and grant examples that work as written (H1 D-1). `tools/guide_walkthrough.py` runs the guide's
  commands in CI (`tests/acceptance/test_guide_walkthrough.py`).

### Added
- Bug-report and feature-request issue forms; wiki framework, page templates and generated wiki source with
  `tools/wiki_publish.py` (both merged after the v1.0.0 tag).
- Phase H1 (hardening, target v1.0.1) and H2 (first real install) in `docs/BUILD-PLAN.md`, with rules for
  maintenance phases; H1 pre-work Q&A `docs/qa/15-h1-prework.md`; findings index and the full engineering
  review under `docs/qa/h1/`. No code change.

## [1.0.0] - 2026-11-20

Phase R1: hardening review, documentation, first stable release. Review dispositions:
`docs/qa/14-r1-prework.md` section 3.

### Added
- `docs/USER-GUIDE.md` and `docs/REFERENCE.md` (every operation, tool, core setting, audit action and event).
- `audit ack` (operator only): acknowledge a recorded audit-chain failure.
- ADR-0012: replacing Hermes compaction is deferred past 1.0.

### Changed
- The model actor is limited in the core to an allow-list of operations (`MODEL_OPS`); `deactivate` is no
  longer a model tool action; module action results reach the model wrapped as `untrusted_data`.
- `module remove --keep-data` keeps data only, never grants. Module ids may not end in `_`.
- `inbox` requests `core.read`: subscribing to `*` or `core.*` events needs it. Grant it after upgrading.
- `resources import_preview` is operator only; cost-class changes are listed and applied as `manual`.
- Every meter quota fires at 100 %; cost quotas need loaded prices.
- Router: free-first after repeated failures; paid pass-through is counted against the budget.
- Supervisor reports modules that stopped since its last pass.

### Security
- Audit log: inter-process append lock and monotonic anchor; failures persist until acknowledged.
- T2 host: bounded message queue and one deadline per call; log streams rotate at 20 MB.
- Broker facades re-check context and grant on every call.
- Trimming keeps 401/403/rejected/blocked lines. Secret leak guard checks encoded forms. Short secrets refused.
- Documented the same-user boundary (DESIGN section 4, SECURITY.md).
- Follow-up review: T2 send deadline and flood kill; guarded facades hide private state; torn audit tails are
  repaired and recorded; leak tripwire no longer blocks ordinary text; all module-written text reaching the
  model is labelled; verify takes the append lock.

## [0.13.0] - 2026-11-20

Phase M12: update and release control for modules.

### Added
- ADR-0011: `module preview` (SBOM delta, patch notes, tree digest); `module update` takes `digest` and refuses
  permission widening without `accept_wider`; SBOM delta stored for every update; manifest `[update] channel`
  and `module check_updates`.
- Bundled `updates` module (M12): scheduled channel checks with one alert per new commit; never applies.

### Security
- M12 security review (`src/switchyard/modules/updates/README.md`): compiled and `.pth` files refused; added
  contributions widen; git isolated from surrounding repositories; checks single and cached; chunked hashing with
  a size cap; rollback widening check, commit restore and pruning; exact patch-note headings.

## [0.12.0] - 2026-11-20

Phase M11: offload connectors.

### Added
- ADR-0010: `net.outbound` broker (`ctx.net.request`): manifest host list, no redirects or proxies, capped bodies,
  audited by host and status only.
- Bundled `offload` module (M11): JevK5, n8n, Claude Code and Codex connectors with declared license class, target
  and data sent; non-open connectors off until allowed by name; payload fields enforced.

### Security
- M11 security review (`src/switchyard/modules/offload/README.md`): Claude Code runs with no tools and agent CLIs
  in an empty working directory (process broker `cwd`); total request deadline; short responses and malformed
  URLs are failures.

## [0.11.0] - 2026-11-20

Phase M10: security testing connectors.

### Added
- Bundled `scanner` module (M10): gitleaks, bandit, pip-audit, osv-scanner, semgrep and trivy as external processes
  on a schedule or on demand; normalised, de-duplicated findings; failures reported as findings; alerts via
  `notify`.

### Security
- M10 security review (`src/switchyard/modules/scanner/README.md`): the process broker writes output to files,
  caps it, decodes leniently and kills the whole process tree on timeout; empty output, oversize output and too
  many findings are failures; semgrep messages are not stored; one scan at a time; skipped scheduled runs are
  audited.

## [0.10.0] - 2026-11-20

Phase M9: dashboard, reporting and notifications.

### Added
- ADR-0009: `notify` broker (`ctx.notify.send`), `report show {kind}` (health, usage, security, changes), control API
  started by the Hermes adapter when `[api] enabled`, API responses redacted.
- Bundled `inbox` module (M9) and a Switchyard dashboard tab (`dashboard/`: modules, inbox, reports).

### Security
- M9 security review (`src/switchyard/modules/inbox/README.md`): the API Hermes starts serves a dashboard profile
  only (no grants or config); severity-aware inbox pruning; redact before truncating; redacted API errors;
  reserved module ids; no address reuse on the API port; a failed API start no longer stops the tick.

## [0.9.0] - 2026-11-20

Phase M8: token economy (trimming).

### Added
- ADR-0008: `hermes.output` capability and deletion-only output transforms (`ctx.hermes_transform`): modules choose
  lines, the core rebuilds output and always keeps errors, exit codes and paths.
- Bundled `trimmer` module (M8): shortens long terminal and tool output; reduction measured on recorded fixtures.

### Security
- M8 security review (`src/switchyard/modules/trimmer/README.md`): linear-time must-keep patterns and long-line
  bound; carriage-return collapse never hides errors; coalesced ranges; fail open over the must-keep cap; more
  exit-code and error forms; progress-only shape dedupe; file-writing tools excluded; hung transforms paused;
  duplicate-key JSON left alone.

## [0.8.0] - 2026-11-20

Phase M7: workers, personas and teams.

### Added
- ADR-0007: `hermes.delegation` capability and a `switchyard` Hermes delegation backend (`ctx.hermes_delegation`);
  `subagent_start` observer hook with a goal digest; `delegated` marker for routed children's requests.
- Bundled `workers` module (M7): worker roles bound to a model pool or a Hermes profile (persona), teams, a
  restart-safe ledger, stuck-worker and repeated-delegation detection.
- Router `explain` takes a `consumer`; requests from routed children are routed within their role's consumer.

### Security
- M7 security review (`src/switchyard/modules/workers/README.md`): routed children's requests are routed and
  charged per request within the role's consumer; paid personas need `llm.paid`; the child marker is consumed
  once, cleared with its owner and removed on `subagent_stop`; ledger pruning covers running rows; goal digests
  fold case and punctuation.

## [0.7.0] - 2026-11-20

Phase M6: supervisor.

### Added
- ADR-0006: `schedule` capability (`ctx.schedule.every`), `core.read` capability (`ctx.core`: module states,
  audit verification), and `pre_llm_call` turn gates (`ctx.hermes_gate`; first reason blocks; fail open).
- Bundled `supervisor` module (M6): scheduled deterministic checks (failed modules, audit chain, quotas, router
  pass-throughs), de-duplicated findings with automatic resolution, `supervisor.alert` events; no LLM calls.
- Router `hard_stop` (opt-in): blocks a turn when only a ruled-out model is left.

### Security
- M6 security review (`src/switchyard/modules/supervisor/README.md`): the router gate blocks only with positive
  registry knowledge and works with Hermes's real `pre_llm_call` arguments; gates return reason codes and the
  core writes the block message; scheduled jobs run time-bounded on per-module workers without the core lock;
  hooks use per-module pools; revoking a required capability deactivates the module; audit verification for
  modules is cached.

### Fixed
- Control API: a request with `Transfer-Encoding` no longer resets the connection on Windows before the `400`.

## [0.6.0] - 2026-11-20

Phase M5: skill activation manager.

### Added
- `hermes.config.write` broker (ADR-0005, `ctx.hermes_config`): allow-listed Hermes config keys written
  through Hermes's public config API, each change backed up, audited, read back and rolled back on failure;
  `revert` restores any backup.
- Bundled `activation` module (M5): skill inventory with prompt cost, presets (names, categories, `*`),
  index-size benchmark, timed presets that restore the previous state, restore and undo.

### Security
- M5 security review (`src/switchyard/modules/activation/README.md`): `plugins.disabled` is not writable;
  ending a preset undoes only its own changes (edits made since are kept, drift audited) and no longer
  depends on backup files; expired presets end before a new one applies; essential skills are never written.

## [0.5.0] - 2026-11-20

Phase M4: metering, quotas and budgets.

### Added
- Bundled `meter` module (M4): counts every Hermes API response by day, hour, provider and model (tokens
  exactly as reported, errors, subagent runs, estimated cost from models.dev prices); opt-in quotas on
  requests, tokens or USD per day or month with thresholds that fire once per period (`meter.threshold`,
  `meter.exhausted`); burn-rate forecast. Stores no text.
- Router cools an exhausted quota's scope down until the period ends.
- Manifest `capabilities.optional`: requested capabilities that auto-start does not wait for.

### Changed
- Bridge (ADR-0004 decision 6): observer hooks hand modules metadata only (no message text, conversation,
  tool traces or raw SDK objects); `subagent_stop` is forwarded.
- CI: CodeQL runs through GitHub's default setup; the conflicting advanced job was removed.

### Security
- M4 security review (`src/switchyard/modules/meter/README.md`): observer payloads use an allow-list (a
  Hermes lease token was forwarded); the router applies exhausted quota scopes on every path and audits
  pass-through; `llm.free` is checked on every request; quota changes are serialized with threshold checks.

## [0.4.0] - 2026-11-20

Phase M3: router and failover.

### Added
- Hermes hook bridge (ADR-0004): modules granted `hermes.hooks` observe `pre_llm_call`, `pre_api_request`,
  `post_api_request`, `api_request_error`, `post_llm_call` and register `llm_request` middleware that may
  change only the request's `model`; failures are isolated and audited. `ctx.call` runs another module's
  read-only action; `ctx.has(capability)` checks a grant without an audit record.
- Bundled `router` module (M3): picks the model for each Hermes request from the consumer's registry pool
  within the active provider: tiers T1-T5 by request size, free and self-hosted first, paid only with the
  `llm.paid` grant + a tier rule + daily budget (each paid choice audited), pins, failover with cool-down
  across Hermes retries, bounded per turn. Decisions keep no prompt text.

### Security
- M3 security review (`src/switchyard/modules/router/README.md`): failover now cools down the resource
  actually sent; a paid configured model can no longer bypass the paid gate on pass-through; bridge
  callbacks get deep copies, only `model` is adopted, calls are time-bounded (2 s); paid choice and charge are
  atomic; request-caused 4xx errors no longer cool resources down.

## [0.3.0] - 2026-11-19

Phase M2: resource registry and pools.

### Added
- `ctx.fs` file-read broker for `fs.read` (ADR-0003): absolute regular files only, size-capped, JSON depth
  limit, audited by path.
- M2 bundled `resources` module: registry of models, endpoints, agents and tools; pools; consumer bindings;
  `resolve`; reviewed imports (preview, then human apply) from the Hermes models.dev cache and catalog files;
  imported resources start disabled.

### Security
- M2 security review (`src/switchyard/modules/resources/README.md`): `ctx.fs` refuses UNC and device paths on
  Windows and checks the grant before any file-system call (a UNC path could leak NTLM credentials); the model
  can no longer choose import paths; JSON is screened before parsing; one pending import per source; failed
  reads are audited.

## [0.2.0] - 2026-11-19

Phase M1: secrets.

### Added
- Module actions (`ctx.register_action`, operation `module action`; the Hermes model tool runs read-only
  actions only) and module-provided secret backends (`ctx.provide_secret_backend`,
  `contributes.secret_backends`; trusted in-process modules only). ADR-0002.
- M1 bundled `secrets` module: Windows Credential Manager (ctypes), macOS keychain (read), Secret Service
  via `secret-tool`, Vaultwarden via `bw`, development env backend (off by default); age and expiry by name;
  rotation of generated values; `secrets.status` panel. No new dependencies.
- `ctx.config`, `ctx.spawn` (process broker), `ctx.audit`; `run_contract(settings=...)`; `[modules.<id>]`
  tables in `config.toml`. Auto modules wait for their grants instead of failing.

### Security
- M1 security review (`src/switchyard/modules/secrets/README.md`): helper programs are never taken from the
  working directory (Windows `shutil.which` searched it first, exposing `BW_SESSION` to a planted `bw.cmd`);
  rotation refuses when an earlier backend still serves the name; action results are redacted as values;
  stricter manifest, settings and argument checks.

### Fixed
- The control API answers `PUT`, `PATCH`, `DELETE` and `OPTIONS` with a JSON 501 after reading the body.

## [0.1.0] - 2026-11-19

Phase M0: the core framework.

### Added
- `switchyard` package (phase M0, part 1): data-directory resolution, core configuration (`config.toml`),
  manifest loader returning a typed `Manifest` with entry-path containment checks, error hierarchy.
- Policy engine (default deny, manifest-bounded grants, `deny:<capability>` module policies, host and
  secret-name allow-lists, audited decisions) and `ModuleContext` (declared streams and panels only,
  namespaced events, capability-gated brokers, `close()` revokes the context).
- State store (SQLite WAL, transactional numbered migrations with backup, persistent grants, module tables
  confined by the SQLite authorizer) and hash-chained audit log (fsync per record, rotation, head anchor
  for truncation detection, redaction, fail-closed on a torn last record).
- Event bus (typed dotted names, per-handler data copies, isolated and audited handler failures, depth
  limit) and scheduler (time/every, 5-field cron, event, usage and capacity triggers; one run at a time,
  minimum interval, counted skips).
- Module lifecycle manager (T1): discovery with trust roots, per-module import packages, fail-closed
  activation and health, idle stop for auto modules, persistent modes, removal with or without data;
  JSON Lines log sink with redaction; panel registry; `ctx.state`.
- T2 subprocess host: length-prefixed JSON-RPC over stdio (1 MiB frames), scrubbed child environment,
  per-call timeouts, child killed on any protocol violation; module context proxied through the same
  policy and confinement checks as in-process modules.
- Secrets broker interface: `secret://` references, policy-checked use with fail-closed backends, leak
  blocking on results, no value in exception context or traceback locals, redactor with default token
  patterns; test-only memory backend.
- Host profiler (CPU, RAM, disk, GPU hint; `tiny`/`laptop`/`workstation`/`server`) and capacity metrics
  for capacity triggers, without subprocesses or network calls.
- `Core` (wires every component for one data directory; audit head anchor kept in `state.db` and
  checked at startup) and the shared operations table used by the CLI, the API and Hermes.
- `switchyard` CLI generated from the operations table (routes through a running daemon, offline-safe
  operations run directly) and the hardened loopback control API (`switchyard api serve`).
- Hermes plugin adapter: model tools (read and run only; no grants), `/switchyard` slash command,
  `hermes switchyard` CLI command, daily audit verification, redaction patterns; validated with
  `hermes plugins validate`. One hosting process per data directory via an OS file lock.
- Update control for git-installed modules: pinned commit fetch (https only, no hooks, verified HEAD),
  staged manifest checks (same id, same pinned source), swap with health check and automatic rollback,
  manual rollback.
- Module contract suite `switchyard.contract.run_contract`; the template module passes it in-process and
  under the subprocess host. End-to-end M0 acceptance tests across CLI, API and Hermes adapter.
- Coverage gate (90%) on `src/switchyard`; mypy strict and bandit now include `src/`.

### Changed
- The manifest schema moved to `src/switchyard/schemas/module.schema.json` so it ships in the wheel.
  `tools/validate_manifest.py` is now a thin CLI over `switchyard.manifest`.

### Fixed
- Module ids containing `__` are rejected; they could have collided with another module's state tables.
- Schema `pattern` checks used Python's `$`, which accepts a trailing newline; they now follow JSON Schema
  semantics (a module id such as `"example\n"` is rejected).
- Module SQL could not use `count(*)`: SQLite reports no database name for that read, and the authorizer
  denied it.

### Security
- M0 security review (section 6 of `docs/modules/m0-core.md`): module SQL statements now have a work budget
  and a 10 000-row result cap; staged updates containing symlinks are refused; on Windows the API token file
  gets a single-user ACL (inheritance removed), and the server refuses to start if that fails.

## [0.0.1] - 2026-11-19

Repository bootstrap (phase P0). No runtime code.

### Added
- Design, build plan, module catalog, pre-engagement Q&A and third-party license review.
- Module manifest schema, stdlib validator, module template and contract tests.
- CI, security scanning, release and Dependabot configuration.

### Changed
- Tooling is installed from a hash-pinned `requirements-dev.txt`; `ci-required` and `security-required` gate jobs added.
- Secret scanning runs the pinned gitleaks CLI. Repository moved to the `vicberger-com` organization.

[Unreleased]: https://github.com/vicberger-com/hermes-signalbox/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/vicberger-com/hermes-signalbox/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/vicberger-com/hermes-signalbox/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/vicberger-com/hermes-signalbox/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.13.0...v1.0.0
[0.13.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vicberger-com/hermes-signalbox/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/vicberger-com/hermes-signalbox/releases/tag/v0.0.1
