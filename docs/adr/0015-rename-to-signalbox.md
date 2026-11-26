# ADR-0015: Rename to Signalbox, and the upgrade path from Switchyard 1.0.x

Status: accepted, 2026-11-25. Phase: H5. Q&A: [19-h5-prework.md](../qa/19-h5-prework.md) questions 6, 7 and 10.

## Context

Two other plugins in the Hermes Desktop catalog use the name "switchyard". One registers the same `/switchyard`
command, so whichever loads last silently wins (reported upstream as NousResearch/hermes-agent#160166). The
operator chose to rename before any public announcement: the new name is **signalbox**. Checked on 2026-11-25:
no catalog entry or built-in command uses `signalbox`, and PyPI has no `hermes-signalbox`. PyPI does have an
unrelated `signalbox` package.

## Decision

1. **Names.** Plugin, slash command, Hermes CLI command, dashboard tab and toolset: `signalbox`. Model tools:
   `signalbox_*`. Distribution and repository: `hermes-signalbox`. Import package: `hermes_signalbox`, not
   `signalbox`, so the unrelated PyPI package can never shadow it. Console script: `hermes-signalbox`, for the
   same reason. Error base class: `SignalboxError`. (R-1)
2. **Clean break** for commands, tool names, the import package and the module API. Only test installs of 1.0.x
   exist and no third-party module is published, so aliases would keep the collision alive for no user. (R-2)
3. **Deprecated, still read in 1.1.x:**
   - the `SWITCHYARD_DATA_DIR` and `SWITCHYARD_SECRET_<NAME>` variables: the `SIGNALBOX_` name wins, and the old
     one logs and warns (`legacy.legacy_env`);
   - secrets stored under the old keychain service or credential prefix: read only when the new name has no
     entry, and only on "not found". A locked or failing backend still fails closed and never falls through.
     Writes go to the new name only. (R-2)
4. **Data directory copy** (`legacy.migrate_data_dir`, called by `Core` before it opens the store), only for the
   default locations and only when the new directory has no `state.db`:
   - exactly one candidate: siblings `agent-plugin-switchyard-*` in Hermes's `plugin-data`, or `switchyard` next
     to the platform default;
   - the old host lock is held for the whole copy, and the directory is re-checked under the lock, so a second
     Signalbox process that finished first is not copied over;
   - the copy goes to `<new>.migrating`, skips runtime files (`host.lock`, `api.port`, `api.token`), and is
     renamed into place only after its audit chain verifies;
   - `core.migrated` (`from`, `records`) is appended once the store is open;
   - the old directory is left as it was, so 1.0.3 can be reinstalled (rollback).
   Refusals raise `ConfigError` and write nothing: the old directory is in use, its audit does not verify,
   several candidates exist, or the new directory is not empty. (R-3)
5. **Version** 1.1.0, listed as breaking in the CHANGELOG and in [UPGRADING-1.1.md](../UPGRADING-1.1.md). (R-4)
6. **Guard.** `tests/core/test_h5_rename.py` fails on any line naming the old plugin outside an allow-list:
   history (CHANGELOG, Q&A files, ADRs 0001-0015), the upgrade code and guide, one "formerly" line in the README,
   and links into the v1.0.0 tag.

## Consequences

- Users type new commands; scripts and saved prompts need editing (UPGRADING-1.1.md lists them).
- Until the repository is renamed on GitHub, links to `vicberger-com/hermes-signalbox` do not resolve. The
  operator renames it before the release PR; GitHub then redirects the old URLs.
- The deprecated variables and the secret-name fallback are removed in 1.2.0.
- Earlier ADRs and Q&A files keep the old name as history.
