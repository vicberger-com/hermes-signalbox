# User guide

Switchyard is a Hermes plugin with a small core and modules you switch on one at a time. Nothing a module does is
allowed until you grant it, and everything that changes is written to a hash-chained audit log. Command and
setting details: [REFERENCE.md](REFERENCE.md). Security model and its limits: [DESIGN.md](DESIGN.md) section 4.

## 1. Install

Needs Hermes Agent 0.22 or newer and Python 3.11 or newer. Switchyard has no Python dependencies.

```bash
# pin an exact release commit (recommended): see the release page for the SHA of a tag
hermes plugins install vicberger-com/hermes-switchyard --ref <40-character commit SHA>
# or with pip, which also installs the `switchyard` command
pip install "git+https://github.com/vicberger-com/hermes-switchyard@<40-character commit SHA>"
```

Releases carry `SHA256SUMS`, a CycloneDX SBOM of what the wheel installs, and a build provenance attestation
(`gh attestation verify <file> -R vicberger-com/hermes-switchyard`). Pin a commit SHA, not a tag name, for
both routes: tags are annotated but not yet signed.

The two routes differ in one way: Hermes 0.23 shows a plugin's dashboard tab only for plugins installed into a
plugins directory, so the Switchyard tab (section 5) needs `hermes plugins install`. A pip install provides the
plugin, the `switchyard` command and the model tools, without the tab; the wheel carries the dashboard files
under `switchyard/_plugin/` for when Hermes supports that.

## 2. First run

**Which data directory.** Switchyard keeps its state, grants, audit log and `config.toml` in one data directory.
A Hermes session uses the profile's plugin data directory; the `switchyard` command uses a platform default
(`%LOCALAPPDATA%\switchyard`, `~/Library/Application Support/switchyard` or `~/.local/share/switchyard`). These
are **two different stores** unless you point both at one: set `SWITCHYARD_DATA_DIR` (or pass `--data-dir`, which wins over the variable) to
the same absolute path everywhere. `switchyard config show` prints the directory in use and why it was chosen
(`data_dir_source`).

**Which process hosts modules.** Only one process hosts modules for a data directory: the first Hermes session
that opens it, or `switchyard api serve`. Commands marked `[daemon]` in `switchyard <noun> --help` (activate,
deactivate, health, panel, action, update, preview, rollback, check_updates, report) need that hosting process
with its loopback API. Other commands (list, show, grant, revoke, mode, remove, audit, config) work directly on
the data directory. A process that runs turns without hosting writes one `core.not_hosting` audit record.

For the commands in this guide, start the daemon first in its own terminal and leave it running (Ctrl+C stops
it):

```bash
switchyard api serve              # step 0: hosts the modules and the loopback API
```

Then, in another terminal:

```bash
switchyard module list            # every module, its status, mode and requested capabilities
switchyard audit verify           # the audit chain is intact
switchyard config show            # data directory in use, why, and core settings
```

In a Hermes session the same operations are under `/switchyard`, for example `/switchyard module list`.
Exit codes: 0 success, 1 error or a failed result, 2 usage error, 3 capability denied.

## 3. Grant capabilities and activate a module

Each module's README lists what it requests and why. A module starts only when every capability it needs to
start is granted; `module show` lists any that are missing under `missing_grants`. Optional capabilities turn
on extra features and can be granted later.

| Module | Needed to start | Optional | Default mode |
|---|---|---|---|
| `activation` | `hermes.config.write`, `hermes.hooks`, `ui.panel` | | auto |
| `inbox` | `core.read`, `ui.panel` | | auto |
| `meter` | `hermes.hooks`, `ui.panel` | `fs.read` | auto |
| `offload` | `net.outbound`, `ui.panel` | `process.spawn` | manual |
| `resources` | `fs.read`, `ui.panel` | | auto |
| `router` | `hermes.hooks`, `ui.panel` | `llm.free`, `llm.paid` | auto |
| `scanner` | `process.spawn`, `schedule`, `ui.panel` | `notify` | manual |
| `secrets` | `process.spawn`, `secrets.read`, `ui.panel` | | auto |
| `supervisor` | `core.read`, `schedule`, `ui.panel` | | auto |
| `trimmer` | `hermes.output`, `ui.panel` | | manual |
| `updates` | `core.read`, `schedule`, `ui.panel` | `notify` | manual |
| `workers` | `hermes.delegation`, `hermes.hooks`, `schedule`, `ui.panel` | `llm.paid` | auto |

Grant only what you want the module to do, then start it (the daemon from section 2 must be running):

```bash
switchyard module show router
switchyard module grant router --capability hermes.hooks
switchyard module grant router --capability ui.panel
switchyard module activate router               # [daemon]
switchyard module health router                 # [daemon]
switchyard module mode router --mode auto       # start it with every hosting process
```

`module revoke` withdraws a capability (a module that needs it stops). `module mode <id> --mode disabled` keeps a
module from starting. Removing a module (`module remove`) always drops its grants; `--keep-data` keeps only its
stored data.

Module settings live in `<data_dir>/config.toml` under `[modules.<id>]`; each module README lists its keys.
Restart the hosting process after editing them.

## 4. What the model may do

Hermes's model gets three tools: `switchyard_modules` (list, show, activate, health, and read-only module
actions), `switchyard_audit` (verify, tail) and `switchyard_host`. The model may start only modules you set to
`auto` mode whose required capabilities you granted; a module you keep `manual` is yours to start. Everything else (grants, modes, removal,
deactivation, updates, budgets, settings, acknowledgements) is for you only, and the core refuses it for the
model actor. Module output reaches the model labelled as untrusted data.

These rules apply to the Switchyard tools. A model that also has an unrestricted shell running as your user can
do what your user can, including running `switchyard` itself; use Hermes's own command approval or sandboxing
for that.

## 5. Dashboard

Set `[api] enabled = true` in `config.toml` and restart Hermes. The Hermes dashboard then shows a Switchyard tab
(module status, panels, reports, the inbox). Requests go through Hermes's authenticated dashboard to a loopback
API that accepts a fixed allow-list of read operations plus activate, deactivate and inbox acknowledgements.

## 6. Notifications and reports

The `inbox` module collects alerts from the supervisor, meter, scanner, workers and updates modules:

```bash
switchyard module grant inbox --capability core.read
switchyard module grant inbox --capability ui.panel
switchyard module activate inbox                # [daemon]
```

Reports (`--kind` is `health`, `usage`, `security` or `changes`; all need the daemon):

```bash
switchyard report show --kind health
switchyard report show --kind security
```

## 7. Updates

Bundled modules update with Switchyard itself (`hermes plugins update switchyard`). Modules you installed
from git under `<data_dir>/modules` are updated by commit:

```bash
switchyard module check_updates                          # [daemon] installed commit vs the head of each channel
switchyard module preview <id> --ref <sha>               # [daemon] files changed, new permissions, notes, digest
switchyard module update <id> --ref <sha> --digest <digest>
switchyard module rollback <id>
```

Updates run git. Switchyard uses the first git on `PATH` that it can actually run (on Windows with Hermes
Desktop, the packaged copy that comes first on `PATH` cannot be run by other programs, so a Git for Windows
install behind it is used). To choose one, set `[tools] git = "<absolute path>"` in `config.toml`;
`switchyard config show` prints the git in use.

An update that adds capabilities, hosts, secrets or contributions, or weakens isolation, is refused unless you
pass `--accept-wider`. A failed health check rolls the update back. The `updates` module checks on a schedule
and alerts; it never installs.

## 8. Audit log

```bash
switchyard audit tail --n 50
switchyard audit verify
```

If verification fails, the failure is recorded and reported until you investigate and run
`switchyard audit ack`. The audit log and its anchor are on your disk: they detect changes, but someone who can
rewrite both files as your user can forge history.

## 9. Uninstall

```bash
switchyard module list                                    # deactivate anything you no longer want first
hermes plugins remove switchyard                          # or: pip uninstall hermes-switchyard
```

The data directory (audit log, state, logs, `config.toml`) is left in place; delete it yourself if you do not
need the audit history.
