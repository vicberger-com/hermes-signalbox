# ADR-0014: Which Hermes process hosts the modules

Status: accepted, 2026-11-24. Phase: H4. Q&A: [18-h4-prework.md](../qa/18-h4-prework.md) question 4.
Amends the "Hosting" paragraph of [m0-core.md](../modules/m0-core.md) and [ADR-0004](0004-hermes-bridge.md).

## Context

One process per data directory hosts the modules: it holds the OS lock on `host.lock`, runs hooks, gates,
transforms, schedules and the loopback API. Up to v1.0.2 the Hermes adapter built its core with "host if the
lock is free" in every process that loaded the plugin, and decided once, at plugin load.

Read in the Hermes source at tags v0.22.0 to v0.23.3 (2026-11-24):

- Hermes loads plugins in many processes: the gateway, agent-running commands, and one-shot commands that
  resolve a plugin CLI command or read gateway configuration (`hermes_cli/main.py`, `gateway/config.py`).
- In v0.23.3 every chat turn runs in the gateway (`hermes_cli/main.py`, `_chat_runs_at_gateway`).
- The gateway's marker environment variable is inherited by every shell the gateway starts
  (`hermes_cli/cli_config_load.py`), so it does not identify the gateway process.
- `gateway.status.owns_gateway_runtime_lock()` answers for the calling process only. The function exists at
  every tag from v0.22.0, and `gateway.status` is in the published plugin API (`hermes_cli/data/plugin_api.json`,
  read at v0.23.2 and v0.23.3; v0.22.0 has no such file).
- `VALID_HOOKS` has no gateway-start hook. Turn-time hooks fire only in a process that runs a turn.
- The gateway discovers plugins (`gateway/config.py`, `gateway/run_startup.py`) and takes its runtime lock
  (`gateway/run_bootstrap.py`) in separate startup steps. The adapter does not rely on their order.

Finding R1-F8 (v1.0.2 acceptance install): a one-shot command that loaded the plugin while the lock was free
became the host for its few seconds of life. A gateway that started in that window found the lock taken, never
tried again, and ran every turn without gates. `hermes gateway restart` is such a command, so the guide's own
restart step produced it.

## Decision

1. **Loading the plugin never makes a process the host.** The adapter builds its core with `hosting=False`.
2. **A process may host when one of two things is true.**
   - It is the gateway runtime: `owns_gateway_runtime_lock()` returns `True`. The adapter looks
     `gateway.status` up in `sys.modules` and never imports it: a process that has not loaded the gateway code
     cannot own the lock, and a one-shot command pays nothing. A missing function or an exception counts as
     "no".
   - It has run a turn itself: a hook, the `llm_request` middleware, an output transform, a model tool or the
     `/switchyard` slash command fired in it. This covers Hermes builds and commands that run turns outside a
     gateway (ACP, the TUI backend, a plugin host process) without naming them.
   The plugin CLI command (`hermes switchyard ...`) is not such a signal.
3. **A process that may host takes the lock when it is free**, records `core.hosting_acquired` with its pid,
   starts the `auto` modules and, when `[api] enabled`, the loopback API. The first turn-time call in a process
   tries this before it dispatches, so the gates apply to that turn.
4. **It keeps trying.** The adapter's daemon thread runs in every process that loaded the plugin. While the
   process does not host, it checks every `HOST_RETRY_SECONDS` (5 s) whether the process may host and, if so,
   tries the lock. While it hosts, it ticks the core as before.
5. **Who hosts is visible.** The host writes its pid to the core `meta` table and removes it on close.
   `Core.host_pid()` reports it only while the lock is held (a process that died leaves the record, not the
   lock). `config show` prints `hosting.here` and `hosting.pid`; `module show` and `module health` carry
   `host_pid`.
6. **Unchanged:** `switchyard api serve` requires hosting, the offline CLI never hosts, and `Core()` used as a
   library hosts when the lock is free.

## Unload (R1-F14)

Read in the same source: `PluginContext.on_unload(callback)` exists at every tag from v0.22.0. Hermes runs the
callbacks, newest first, when it unloads a plugin in a running process: a targeted unload (disable, uninstall)
and the unload-all that precedes a forced rediscovery (`hermes_cli/plugins_ledger.py`; the gateway's
`reload-plugins` control verb in `gateway/run_plugin_rewire.py`, which `hermes plugins enable` and
`hermes plugins disable` ask a running gateway for, `hermes_cli/plugins_cmd.py`, v0.23.3).

Up to v1.0.2 the adapter registered no such callback. Its cleanup ran only when the plugin was registered
again or the process exited, so after a disable and uninstall the gateway kept the host lock, the loopback API
and the active modules until it was restarted. (The acceptance note that `HermesAdapter.close()` did not close
the core was not reproduced: it does, and a test pins it. The missing callback is the whole cause.)

7. **`register()` hands Hermes an unload callback** when the context has `on_unload`. The callback stops the
   adapter it was created for: modules are deactivated with reason `unload`, the API stops and its files are
   removed, the driver thread ends, the host lock is released. A callback of an adapter that a later load has
   already replaced closes only that old adapter. The callback never raises.
8. **`Core.close(reason=...)`** records the reason on each `module.deactivated` (`shutdown` by default) and
   runs every release step even when an earlier step raised, so a failed stop cannot keep the host lock.
9. **After unload, references Hermes may still hold do nothing:** hooks and middleware return `None`, tools
   and the slash command answer "core is closed", and nothing is recorded.

A forced rediscovery while the plugin stays enabled therefore stops and restarts the modules, as the
re-registration already did before. A host without `on_unload`, or one whose registration fails
(`core.adapter_error`), keeps the exit-time cleanup only.

## Consequences

- `hermes gateway status`, `hermes gateway restart` and `hermes switchyard ...` write no activation records
  and cannot take hosting away from the gateway.
- If a gateway loads plugins before it owns its runtime lock, the modules start up to one retry period after
  it does.
- A process that runs turns while another one hosts still records `core.not_hosting` once. It now takes over
  when the host exits.
- With no gateway and no turn yet, nothing hosts: live operations from the slash command make the process a
  host; the standalone CLI still needs `switchyard api serve`.
- `module health` results gain `host_pid`. Code that compared the whole result must read `ok` and `detail`.
- After `hermes plugins disable switchyard` or an uninstall, a running gateway releases the data directory
  as soon as Hermes unloads the plugin in it; no restart is needed for that.
- A module's `mode` and status are still read when the plugin loads; a change made between load and a late
  takeover is the subject of R1-F9 (work package 3).

## Alternatives considered

- **Read the command line** (`gateway run`): launchers, service managers and the Desktop app start the gateway
  in different ways; Hermes's own check is the contract.
- **Take the lock after a delay:** a one-shot command that waits for the gateway (a restart) outlives any
  delay that is short enough to be useful.
- **Host only on the first turn:** `auto` modules, schedules and the dashboard API would not start with the
  gateway.
