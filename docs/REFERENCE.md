# Reference

Written by hand against the code (operations table: `hermes_signalbox.ops.OPERATIONS`; a test checks that every
operation is listed here). How to use them: [USER-GUIDE.md](USER-GUIDE.md).

Global CLI options, before the noun: `--json` (print results as JSON) and `--data-dir PATH` (use this data
directory; it wins over `SIGNALBOX_DATA_DIR`).

Output formats (1.1): without `--json` the CLI prints text for a person: a summary line first, then a table
or a short list with plain-language labels, local times and a next step where one exists. A `/signalbox` chat
reply is the same content as Markdown; add `json=true` for the payload (`/signalbox module list json=true`).
`--json`, `json=true` and the model tools return the operation's payload unchanged, so scripts should read
those and never the text form. The labels come from one table (`hermes_signalbox.labels`): every capability,
status, mode, severity, actor and core audit action has a label and a one-sentence meaning.

Module states: `verified` (manifest valid, not running), `active` (running), `stopped` (deactivated or idle-stopped)
and `failed` (activation, health or a hook failed; `error` names the exception class). Modes: `manual` (only the
operator starts it), `auto` (started with the host; the model may start it too) and `disabled` (never started).
A bundled module's default mode is its manifest's `lifecycle.activation`.

## Operations

The same operations run from the CLI (`signalbox <noun> <verb>`), the `/signalbox` slash command in Hermes,
and the loopback API (`POST /v1/<noun>/<verb>` with a JSON body). "Model" marks what the `hermes` actor (the
model's tools) may run; the core refuses everything else for it. "Dashboard" marks what the dashboard's API
profile accepts. Also: `hermes-signalbox version`, `hermes-signalbox api serve [--port N]` (run the hosting daemon and API;
SIGTERM, Ctrl+C and Ctrl+Break stop it and remove `api.port` and `api.token`).

Operations that need a running module instance (`module activate`, `deactivate`, `health`, `panel`,
`action`, `update`, `preview`, `rollback`, `check_updates`, `report show`) need the hosting process for the
data directory and are marked `[daemon]` in `signalbox <noun> --help`. `module list` and `module show` include
`missing_grants` (capabilities needed to start that are not granted). `config show` prints `data_dir` and
`data_dir_source` (why that directory was chosen) and nested settings as `section.key: value`.

Which process hosts: `config show` prints `hosting.here` (whether the answering process hosts the modules) and
`hosting.pid` (the process that does; `None` when nobody hosts the data directory). `module show` and
`module health` carry the same pid as `host_pid`.

CLI exit codes: 0 success; 1 operation error, or a result that reports failure (`status: failed`, `ok: false`);
2 usage error (an unknown name or an invalid value, including an unknown capability name); 3 refused by policy
(a capability not granted, or something the module's manifest does not declare).

`report show --kind usage` has one section per usage module (`meter`, `router`, `trimmer`, `workers`); a
module that cannot report shows `unavailable` with the reason `not installed`, `not active` or `action failed`.

Every report carries `purpose` (the question it answers) and `summary` (1.1): `headline` (one sentence),
`counts` (the numbers behind it) and `lines` (what needs attention). The summary is computed from the report
payload alone, so the same data always gives the same text.

| Kind | Question it answers | Headline, for example |
|---|---|---|
| `health` | Is everything working, and what needs your attention? | `2 of 12 modules running · 0 failed · 10 waiting for permissions` |
| `usage` | What did Hermes route and use, and what did it cost? | `1 of 4 usage sources reporting` |
| `security` | Has the audit log been tampered with, and what was refused? | `Audit log intact: 72 records, chain verified · 3 recent refusals` |
| `changes` | Who changed what, and when? | `2 changes recorded; latest: Dashboard started router` |

| Command | Parameters | What it does | Model | Dashboard |
|---|---|---|---|---|
| `audit ack` |  | Acknowledge a recorded audit-chain failure after investigating it (operator only). |  |  |
| `audit tail` | `--n` (optional) | Show the most recent audit records. | yes | yes |
| `audit verify` |  | Verify the audit hash chain against the stored head anchor. | yes | yes |
| `config show` |  | Show the effective core configuration (no secret values exist in it). | yes |  |
| `host profile` |  | Show the host profile used to pick capacity defaults. | yes | yes |
| `module action` | `id`, `--action`, `--args` (optional) | Run an action a running module registered (ADR-0002). | yes | yes |
| `module activate` | `id` | Start a module (needs the hosting process: daemon or Hermes session). | yes | yes |
| `module check_updates` |  | Compare git-installed modules with the head of their update channel. |  |  |
| `module deactivate` | `id` | Stop a running module. |  | yes |
| `module grant` | `id`, `--capability` | Grant a requested capability to a module. |  |  |
| `module health` | `id` | Run a module's health check. | yes |  |
| `module list` |  | List every discovered module with status, mode and capabilities. | yes | yes |
| `module mode` | `id`, `--mode` | Set activation mode: manual, auto or disabled. |  | yes |
| `module panel` | `id`, `--panel` | Render one of a running module's panels as plain data. | yes | yes |
| `module preview` | `id`, `--ref` | Stage a commit without applying it: SBOM delta, patch notes and tree digest. |  |  |
| `module remove` | `id`, `--keep-data` (optional) | Stop and forget a module; drops its grants, and its data unless keep_data is true. |  |  |
| `module revoke` | `id`, `--capability` | Revoke a capability from a module. |  |  |
| `module rollback` | `id`, `--accept-wider` (optional) | Restore the previous version of a git-installed module; refused if its files changed since they were set aside; reports the health check (exit 1 when it fails). |  |  |
| `module show` | `id` | Show one module, including its declared contributions and live panels. | yes | yes |
| `module update` | `id`, `--ref`, `--digest` (optional), `--accept-wider` (optional), `--allow-downgrade` (optional) | Update a git-installed module to a pinned commit; rolls back if it fails. An older version needs `--allow-downgrade`. |  |  |
| `report show` | `--kind` | Operator report: health, usage, security or changes (redacted; M9). | yes | yes |

## Hermes tools and command

| Name | Arguments | Notes |
|---|---|---|
| `signalbox_modules` | `action`: list, show, activate, health, run; `id`; `name` and `args` for run | `run` reaches read-only module actions only; results are wrapped as `{"untrusted_data": ..., "note": ...}` |
| `signalbox_audit` | `action`: verify, tail; `n` | |
| `signalbox_host` | none | Host profile |
| `/signalbox <noun> <verb> [args]` | as the CLI, `key=value` arguments; `json=true` for the payload | Runs as the operator (`user` actor); replies in Markdown |

## Core settings (`<data_dir>/config.toml`)

| Key | Default | Meaning |
|---|---|---|
| `data_dir` | plugin data directory | Absolute path for all state (also `SIGNALBOX_DATA_DIR`) |
| `[api] enabled` | `false` | Start the loopback control API in the hosting process (needed by the dashboard) |
| `[api] port` | `0` | Port; `0` picks a free one (written to `api.port`) |
| `[log] level` | `INFO` | DEBUG, INFO, WARNING, ERROR |
| `[host] profile` | `auto` | auto, tiny, laptop, workstation, server: capacity defaults |
| `[tools] git` | first runnable `git` on `PATH` | Absolute path of the git used by module updates. When set, only this git is used. `config show` prints the git in use (`tools.git`) |
| `[modules.<id>]` | | Module settings: see each module's README |

## Audit actions

Core actions (detail values are redacted before writing):

`api.start_failed`, `audit.acknowledged`, `audit.verify_failed`, `core.hosting_acquired`, `core.migrated`, `core.not_hosting`, `core.tick_failed`, `event.depth_exceeded`, `event.handler_failed`, `fs.read`, `fs.read_failed`, `hermes.config.rollback`, `hermes.config.write`, `module.action`, `module.activated`, `module.auto_skipped`, `module.deactivate_failed`, `module.deactivated`, `module.delegation_failed`, `module.delegation_refused`, `module.failed`, `module.gate_blocked`, `module.gate_rejected`, `module.hook_failed`, `module.hook_timeout`, `module.job_skipped`, `module.job_timeout`, `module.middleware_rejected`, `module.mode_changed`, `module.notify`, `module.rejected`, `module.reloaded`, `module.removed`, `module.rolled_back`, `module.transform_paused`, `module.update_check_failed`, `module.update_previewed`, `module.update_rejected`, `module.updated`, `module.verified`, `net.request`, `policy.denied`, `policy.grant_refused`, `policy.granted`, `policy.grants_removed`, `policy.revoked`, `process.spawned`, `secret.backend_added`, `secret.backend_removed`, `secret.leak_blocked`, `secret.unavailable`, `secret.used`, `trigger.failed`.

Module actions are recorded as `module.<id>.<name>`:

| Module | Actions |
|---|---|
| `activation` | `module.activation.drift`, `module.activation.expired`, `module.activation.preset_add`, `module.activation.preset_remove` |
| `inbox` | `module.inbox.ack_all` |
| `meter` | `module.meter.quota_add`, `module.meter.quota_remove`, `module.meter.threshold` |
| `offload` | `module.offload.offload` |
| `resources` | `module.resources.bound`, `module.resources.import_applied`, `module.resources.pool_created`, `module.resources.pool_deleted`, `module.resources.pool_member_added`, `module.resources.pool_member_removed`, `module.resources.priority_set`, `module.resources.state_set`, `module.resources.unbound` |
| `router` | `module.router.auto`, `module.router.budget`, `module.router.hard_stop`, `module.router.paid_decision`, `module.router.paid_passthrough`, `module.router.pin`, `module.router.quota_passthrough`, `module.router.rule_add`, `module.router.rule_remove`, `module.router.timeout_charged`, `module.router.timeout_fallback`, `module.router.timeout_passthrough` |
| `scanner` | `module.scanner.scan` |
| `secrets` | `module.secrets.expiry_set`, `module.secrets.rotated` |
| `supervisor` | `module.supervisor.ack`, `module.supervisor.alert` |
| `updates` | `module.updates.checked` |
| `workers` | `module.workers.loop_refused`, `module.workers.role_remove`, `module.workers.role_set`, `module.workers.stuck`, `module.workers.team_remove`, `module.workers.team_set` |

## Events

| Type | Published by | Data |
|---|---|---|
| `core.notify` | notify broker (any module with `notify`) | `module`, `severity`, `title`, `detail` (redacted, capped) |
| `meter.threshold`, `meter.exhausted` | meter | `quota`, `scope`, `metric`, `percent`, `used`, `limit`, `period`, `period_end` |
| `supervisor.alert` | supervisor | `key`, `severity`, `message` |
| `scanner.finding` | scanner | `severity`, `title` |
| `workers.loop` | workers | `role`, `goal_sha` |
| `workers.stuck` | workers | `role`, `child`, `minutes` |
| `trigger.fired`, `trigger.skipped` | scheduler | `trigger`, `owner` (and `reason` when skipped) |
| `module.*`, `module.rejected` | lifecycle | `module` and the audit detail; `path`, `reason` for rejected |

Subscribing to `*` or to `core.*` events needs `core.read`.

## Data directory

| Path | Contents |
|---|---|
| `config.toml` | Settings (you edit it) |
| `state.db` | Grants, module state, audit anchor |
| `audit/` | Hash-chained audit log (`audit-NNNNNN.jsonl`) |
| `logs/` | Per-stream JSON Lines logs, 20 MB per stream plus one rotated file |
| `modules/` | Modules you installed from git (run as subprocesses) |
| `staging/` | Update staging, previous versions (3 kept), SBOM deltas |
| `backup/` | State database backups taken before schema migrations |
| `host.lock`, `api.token`, `api.port` | Hosting lock; API token and port (user-only permissions) |
