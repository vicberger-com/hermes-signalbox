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
pip install "git+https://github.com/vicberger-com/hermes-switchyard@v1.0.0"
```

Releases carry `SHA256SUMS`, a CycloneDX SBOM and a build provenance attestation
(`gh attestation verify <file> -R vicberger-com/hermes-switchyard`).

## 2. First run

Start Hermes. The plugin creates its data directory (the profile's plugin data directory unless you set
`data_dir`) and discovers the bundled modules. None is active and none holds a capability.

```bash
switchyard module list            # every module, its status, mode and requested capabilities
switchyard audit verify           # the audit chain is intact
switchyard config show            # effective core settings
```

In a Hermes session the same operations are under `/switchyard`, for example `/switchyard module list`.

Only one process hosts modules for a data directory (the first Hermes session or `switchyard api serve`).
Other processes read and change stored state, but gates, hooks and transforms run only in the hosting one; a
process that runs turns without hosting writes one `core.not_hosting` audit record.

## 3. Grant capabilities and activate a module

Each module's README lists what it requests and why. Grant only what you want it to do:

```bash
switchyard module show router
switchyard module grant router --capability hermes.hooks
switchyard module activate router
switchyard module mode router --mode auto       # start it with every hosting process
```

`module revoke` withdraws a capability (a module that needs it stops). `module mode <id> --mode disabled` keeps a
module from starting. Removing a module (`module remove`) always drops its grants; `--keep-data` keeps only its
stored data.

Module settings live in `<data_dir>/config.toml` under `[modules.<id>]`; each module README lists its keys.
Restart the hosting process after editing them.

## 4. What the model may do

Hermes's model gets three tools: `switchyard_modules` (list, show, activate, health, and read-only module
actions), `switchyard_audit` (verify, tail) and `switchyard_host`. Everything else (grants, modes, removal,
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

Activate `inbox` (grants `core.read`, `ui.panel`) to collect alerts from the supervisor, meter, scanner,
workers and updates modules. Reports: `switchyard report show --kind health|usage|security|changes`.

## 7. Updates

Bundled modules update with Switchyard itself (`hermes plugins update switchyard`). Modules you installed
from git under `<data_dir>/modules` are updated by commit:

```bash
switchyard module check_updates                          # installed commit vs the head of each channel
switchyard module preview ext --ref <sha>                # files changed, new permissions, notes, digest
switchyard module update ext --ref <sha> --digest <digest>
switchyard module rollback ext
```

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
