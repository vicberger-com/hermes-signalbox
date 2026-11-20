# <Module name>

One paragraph: what it does and for whom.

| | |
|---|---|
| Id | `example` |
| Phase | Mn |
| Isolation | in-process or subprocess |
| License class | open or proprietary-connector |

## Capabilities requested

| Capability | Why it is needed | What breaks without it |
|---|---|---|

## Control surface

| Kind | Name | Purpose |
|---|---|---|
| Tool | | |
| Command | | |
| Panel | | |
| Config key | | |

## Events, logs and reports

Events published and consumed, log streams, report sections, alert conditions.

## Data

What is stored, where, retention, and what removal deletes. State that no secret values are stored.

## Security notes

Inputs treated as untrusted, hosts contacted, secrets used (names only), failure behaviour.

## Update and rollback

Source, verification, health check used after update.

## Contract tests

`tests/test_contract.py` keeps the module's own unit tests and calls `switchyard.contract.run_contract` on
the module directory. It passes `bundled=True` because the template is in-process, which only a module inside this
repository may be; a module shipped on its own sets `isolation = "subprocess"` and drops the flag. A module ships only when the full contract passes (see `docs/modules/m0-core.md`).

## Third-party code

Source, license, what was reused, where it is attributed.
