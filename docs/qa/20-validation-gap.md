# Validation gap analysis (ADR-0016), 2026-11-27

What the operator can see and do today for each module, measured against the five parts ADR-0016 requires.
Sources: each module's README ("Control surface"), `dashboard/dist/index.js`, `dashboard/plugin_api.py`, and
commands run on a real install of the 1.1.0 release candidate on 2026-11-27. This file is the input to the H6
pre-work Q&A; it changes no code.

## Findings that apply to every module

| # | Finding | Evidence |
|---|---|---|
| V-1 | No module has its own screen. The dashboard has Modules, Inbox and Reports | `dashboard/dist/index.js` |
| V-2 | Every module registers a status panel and the plugin API serves it (`GET /panel/{id}/{panel}`), but the page never requests one | No use of `/panel` in `index.js`; `module panel router --panel router.status` returns data |
| V-3 | A panel at the command line is printed as raw keys with Python values (`recent: [{'at': ...`), not readable text | Output of `module panel` on the install |
| V-4 | `config show` lists core settings only. No surface shows a module's settings in effect, their defaults or where a value came from | Output of `config show`; module settings are read from `[modules.<id>]` in `config.toml` |
| V-5 | Module operations ("actions") are reachable only by typing `module action <id> --action <name> --args <JSON>`; nothing lists them outside each README | `ops.py`; READMEs |
| V-6 | Permissions granted and not granted appear in the About panel of the Modules view and in `module show`; granting and revoking are terminal-only by design | Modules view; ADR-0016 "What does not change" |
| V-7 | `audit tail` takes a count only: no filter by module, action or time | `audit tail --help` |
| V-8 | The data directory's `logs/` held one module log (`router.jsonl`) on the install; the others had written none. No surface displays a module log | Directory listing on the install |
| V-9 | Reports (health, usage, security, changes) are organised by kind, not by module; there is no per-module results view over a period | Reports view |
| V-10 | Start and Stop act at once, with no confirmation and no statement of the effect (stopping `router` stops model routing) | Modules view |

## Per module

"Panel" and "actions" mean the module has them; "shown" means a person can read them on some surface without
typing an action name or reading JSON.

| Module | Settings exist | Settings shown | Operations exist | Operations listed or offered | Status panel exists | Status shown in dashboard | Results over time | Log readable |
|---|---|---|---|---|---|---|---|---|
| activation | no table in README | no | yes | no | `activation.status` | no | no | no |
| inbox | `min_severity` | no | yes | Inbox view offers list and acknowledge | `inbox.status` | Inbox view (its own) | Inbox view | no |
| meter | 2 | no | yes | no | `meter.status` | no | Usage report, partly | no |
| offload | 4 | no | yes | no | `offload.status` | no | no | no |
| resources | yes | no | yes | no | `resources.status` | no | no | no |
| router | yes | no | yes | no | `router.status` | no | Usage report, partly | file exists; not shown |
| scanner | yes | no | yes | no | `scanner.status` | no | Security report, partly | no |
| secrets | 5 | no | yes | no | `secrets.status` | no | no | no |
| supervisor | yes | no | yes | no | `supervisor.status` | no | Inbox notices | no |
| trimmer | yes | no | yes | no | `trimmer.status` | no | no | no |
| updates | 1 | no | yes | no | `updates.status` | no | Update state in About | no |
| workers | 4 | no | yes | no | `workers.status` | no | Ledger action only | no |

The "Results over time" column is read from what the Reports and Inbox views are described to show; it was
not checked module by module on the install. Not examined: what each status panel contains and whether it answers "was it done right"; whether each
module records enough to show results over a period; third-party modules.

## Proposed order for H6 (to be settled in its pre-work Q&A)

1. Show what exists: a screen per module that renders its status panel readably, lists its operations with
   their meaning and command, and shows its settings in effect (V-1 to V-5).
2. Logs and audit by module, with filters (V-7, V-8).
3. Results over a period per module, and the standard each is measured against (V-9).
4. Controls: confirmation with the stated effect (V-10); then, per operation and by recorded operator
   decision, which further operations the dashboard may perform itself.
