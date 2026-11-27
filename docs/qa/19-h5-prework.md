# Pre-work Q&A: H5 rename to Signalbox and user-testing usability (v1.1.0)

Date: 2026-11-25. Previous phase: H4 (maintenance), tag v1.0.3.

H5 is a minor-release phase, not a pure maintenance phase: it changes names and adds user-facing behaviour, so it
ships as **v1.1.0** (maintenance rule 6 allows no new behaviour in a patch). Scope was set by the operator on
2026-11-25:

- **Rename** `switchyard` → `signalbox` before any public announcement (decision on the name collision with two
  other plugins in the Hermes catalog; upstream report NousResearch/hermes-agent#160166).
- **User-testing findings** from the first user-level install of v1.0.3: #205, #206, #207, #208, #210. These are
  public issues, presentation only, with no security detail to withhold.
- Release order: rename first, then the usability work on the renamed code, so every new label and help text is
  written once with the final name. One operator usability review and one counted acceptance run close the phase.

This is the first phase under pre-work question 12 and the two new gates (#209).

Answer every question. Take the recommended option, mark it **default accepted**, and continue.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| v1.0.3 user testing | The chat replies, the Modules view, the Reports view and the Inbox present raw machine data with no explanation. The operator, who helped specify the plugin, could not tell what the page offered | #205-#208, #210 in scope; question 12 answered for every surface below |
| M9 pre-work (`10-m9-prework.md`) | Report kinds were specified by input data and redaction only; nothing named a reader or a presentation | Each report gets a stated purpose and a deterministic `summary` |
| #209 | Pre-work question 12, the Presentation gate and the Operator usability gate (every release) | Both gates apply at H5 close |
| H4 | The dashboard tab and `/switchyard` replies need the hosting gateway with `[api] enabled` | The usability review runs on a real Desktop install, the same as the counted runs |
| Rename plan (private record, 2026-11-25) | Inventory at `252137dd`: 293 files, 2,673 occurrences | Rename as one mechanical PR with a guard test |

## 2. Research record

| Topic | Source (date read) | Finding |
|---|---|---|
| Hermes release in use | Desktop 7855, payload ref `8fc03744`; GitHub releases API (2026-11-25) | v0.23.4 stable (2026-11-24); no plugin API change since H4 is relevant to H5 |
| Name collision report | NousResearch/hermes-agent#160166 (2026-11-25) | Open, no maintainer response yet; the rename does not depend on it |
| Name availability | Hermes 7855 catalog and built-in commands; PyPI JSON; GitHub search (2026-11-25) | `signalbox`: 0 catalog or command hits; PyPI `hermes-signalbox` and `hermes_signalbox` free (404); PyPI `signalbox` **taken** by an unrelated package; 0 GitHub repos named `hermes-signalbox` |
| Data that #206/#210 need | `src/switchyard/manifest.py` (`summary`, `version`, `update.source/url/ref/channel`), `updates.py` `check()`/`cached_checks()`, `gitfetch.py` `latest()` (`git ls-remote`), `modules/updates` `check_now` | Description, version and source exist; update checks exist for git modules only and need the `updates` module running; bundled modules update with the plugin |
| Current dashboard | `dashboard/dist/index.js`, `style.css`, `dashboard/plugin_api.py` (v1.0.3) | Buttons always enabled and errors swallowed (`.then(refresh, refresh)`); reports are `JSON.stringify` in a 30rem box; Refresh never re-enters a loading state; the backend allows only activate/deactivate writes |
| Chat replies | `src/switchyard/hermes/__init__.py` slash handler | Every verb returns `json.dumps(result, indent=2)` |
| Accessible tooltips | WAI-ARIA APG tooltip pattern; WCAG 2.2 SC 1.4.13 (Content on Hover or Focus) | Tooltips must open on focus as well as hover, be dismissible (Esc) and hoverable, and supplement a visible label; reasons for a disabled control need `aria-describedby`, not a tooltip alone |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | What is the smallest scope that meets the acceptance criteria? | (a) rename + #205-#208 + #210; (b) also new modules or features | (a): operator scope decision; nothing else | default accepted (operator) |
| 2 | Which capabilities does the module need, and which can be dropped? | | No capability changes. The update check keeps running in the core (`git ls-remote`) when the `updates` module asks; `updates` keeps `core.read` + `schedule` | default accepted |
| 3 | Reuse, adapt or write? | | Write. Plain JS stays (no build step, ADR-0009); no UI library | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | What can go wrong for security? | | Rename: a stale `switchyard` path or env var silently ignored (guard test); migration copying a live data dir (refuse while locked). UI: manifest-supplied links (https only, escaped, host shown, `noopener noreferrer`); the new mode write endpoint (same `_WRITE` guard and `Sec-Fetch-Site` check as activate; audited `actor=api`); a labels endpoint leaking nothing (static) | default accepted |
| 6 | State schema and migration; what is removed on uninstall? | | No schema change. Data dir moves from `agent-plugin-switchyard-<hash>` to `agent-plugin-signalbox-<hash>`: on first load, if the new dir is empty, the old one exists and its `host.lock` is free, **copy** (never move), verify the audit chain in the copy, append `core.migrated`; leave the old dir for rollback; refuse with a message (no partial copy) if locked. Uninstall unchanged | default accepted (R-3) |
| 7 | Control surface | | `/signalbox`, `hermes signalbox`, console script `hermes-signalbox`, import package `hermes_signalbox` (PyPI `signalbox` is taken, R-1), tools `signalbox_*`. Clean break for commands and tools; `SWITCHYARD_*` env vars still read in 1.1.x with a deprecation warning (R-2). New: `json=true` on slash verbs; dashboard `POST /modules/{id}/mode`; a read-only labels route | default accepted |
| 8 | Logs, metrics, report section, alerts | | Reports gain a deterministic `summary` (counts + sentences) per kind; `core.migrated` audit action; no new metrics | default accepted |
| 9 | Update source and rollback check | | Rollback from 1.1.0 to 1.0.3: the old data dir is untouched by migration, so reinstalling 1.0.3 works; documented in USER-GUIDE §9 | default accepted |
| 10 | Does anything need a core contract change (ADR)? | | ADR-0015 (rename and data migration) and an ADR-0009 amendment (presentation layer: labels, mode write, summaries) | default accepted |
| 11 | Operator input needed? | | (1) Rename the GitHub repository before the release PR; (2) re-store the repository-scoped token under the new path (the session tool looks it up by repo path); (3) the usability review and the counted run on the Desktop install | default accepted |
| 12 | Audience and presentation | | See the table below | default accepted |

### Question 12: audience and presentation per surface

| Surface | Reader | Question it answers | Human format (default) |
|---|---|---|---|
| `/signalbox <noun> <verb>` chat reply | Operator in a Hermes chat | Whatever the verb asks (what's installed, is it healthy, what changed) | Markdown: one summary line, then a table or short list with plain labels; raw JSON only with `json=true` (#205) |
| `hermes signalbox ...` text output | Operator at a terminal | Same as chat | The same formatter as chat, in plain text; `--json` unchanged |
| Dashboard intro and help | First-time user | What is this page, what is each view for, what can I do here | A collapsible intro, a help line per view, a "?" panel, a "where do I do X" pointer with copyable commands (#208) |
| Modules view | Operator | What does each module do, is it running, why not, how do I change it, which version, from where, is there an update | A table with description, status, mode (editable), health, version, source and update state; tooltips on every value; a legend; buttons disabled with a reason; inline errors (#206, #210) |
| Reports view | Operator | Health: is it working, what needs attention? Usage: what was routed and what did it cost? Security: tampering or refusals? Changes: who changed what, when? | A summary at the top, then readable sections and tables; local and relative times; repeats grouped; raw JSON collapsed (#207) |
| Inbox view | Operator | What happened that needs my attention? | Time, severity (colour + icon + text), labelled detail fields, Open/Acknowledged/All filter, grouped repeats, a count on the tab, a "what is this" note (#208) |
| Glossary | All of the above | What does this term mean? | One label source for capabilities, statuses, modes, severities and audit actions, served read-only and published in the USER-GUIDE (#208) |

## 4. Work packages

| WP | Scope | Issues |
|---|---|---|
| WP1 | Rename: package, plugin, commands, tools, env vars (old ones deprecated), docs, CI, wheel file list; data-dir migration; ADR-0015; guard test that no `switchyard` survives outside an allow-list | rename plan R-1..R-4 |
| WP2 | Labels and summaries in the core: `labels` module (capabilities, statuses, modes, severities, audit actions) with a completeness test; a `summary` per report kind; a human formatter shared by chat and CLI; `json=true` | #205, #207 (core), #208 (glossary) |
| WP3 | Dashboard Modules view: description, version, source, update state, mode select + backend route, disabled-with-reason buttons, inline errors, tooltips, legend; manifest `homepage`/`docs`/`based_on` (https only) | #206, #210 |
| WP4 | Dashboard Reports and Inbox views and the page help layer: intro, help lines, "?" panels, empty states, Refresh with a loading state and "Updated" time | #207, #208 |
| WP5 | Docs: USER-GUIDE (glossary, dashboard sections, rename and upgrade notes), REFERENCE, MODULES, wiki | all |

## 5. Acceptance (written before code)

- [ ] After the rename, `git grep -i switchyard` matches only the allow-list (CHANGELOG history, migration code and its tests, the deprecation shim, ADR-0015, earlier Q&A files).
- [ ] A v1.0.3 data dir is copied on first load of 1.1.0, the audit chain verifies in the copy, `core.migrated` is recorded, the old dir is byte-identical afterwards; a locked old dir is refused with no partial copy.
- [ ] `SWITCHYARD_DATA_DIR` still works in 1.1.x with a deprecation warning; `SIGNALBOX_DATA_DIR` wins when both are set.
- [ ] Every slash verb returns readable Markdown by default with a summary line; `json=true` returns the previous payload unchanged; model tool output and CLI `--json` are unchanged.
- [ ] Every capability, status, mode, severity and listed audit action has a label (test fails on a missing one).
- [ ] Each report kind has a documented purpose and a deterministic `summary`, fixed by tests on known fixtures (healthy, nothing granted, a failed module, a tampered audit log).
- [ ] Modules view: description, version, source and update state on every row; a module with missing grants has a disabled button with the reason and the grant command; a refused action shows the core's message on the row; mode is settable, audited `module.mode_changed` with `actor=api`, and refused cross-site.
- [ ] Manifest links: only `https://` accepted by the schema; rendered escaped, with `rel="noopener noreferrer"` and the host shown (hostile-manifest test).
- [ ] With `updates` stopped, the dashboard shows "Not checked" and no fetch happens from the dashboard backend.
- [ ] Reports view: no fixed-height inner scroll box; summary first; no raw JSON unless expanded; Refresh shows a loading state and an "Updated" time on every click and is disabled while loading.
- [ ] Inbox view: time shown, Open/Acknowledged/All filter, repeats grouped, no raw `key=value`, open count on the tab.
- [ ] Keyboard-only and screen-reader pass on all three views (tooltips open on focus and close on Esc).
- [ ] **Presentation gate:** every surface in the question 12 table matches its row.
- [ ] **Operator usability gate:** the operator uses chat, CLI and every dashboard view on a real Desktop install of the release candidate; every finding fixed or recorded with a disposition.
- [ ] One counted acceptance run on the 1.1.0 SHA plus an upgrade rehearsal (1.0.3 → 1.1.0 with migration, then uninstall both, 0 differences).

## 6. Dispositions (filled in as each package merges)

| Issue / item | WP | Status |
|---|---|---|
| #205 chat replies and CLI text are raw data | WP2 | Fixed: Markdown chat replies and text CLI output from one formatter; `json=true` and `--json` return the payload unchanged |
| #207 reports have no summary (core part) | WP2 | Fixed: `purpose` and a deterministic `summary` per report kind; the dashboard views follow in WP4 |
| #206 Modules view: silent failures, unexplained values, mode not settable | WP3 | Fixed in #224 (mode route, labels route), #225 (row data) and the Modules view PR: disabled-with-reason buttons, inline errors, mode selector, tooltips, legend |
| #210 Modules view: description, version, source, update state, links | WP3 | Fixed (adapted): shown from `module show` data that never contacts the network. Not built: the plugin-release line and a "Check now" button (a check still needs the `updates` module or `module check_updates`); `based_on` for the bundled modules is filled with the docs package (WP5) |
| #207 Reports view shows raw JSON; Refresh gives no feedback | WP4 | Fixed in #227 (view data) and the views PR: summary first, purpose, tables with local times, raw JSON collapsed and no longer clipped; Refresh is a separate button with a working state and an Updated time |
| #208 page and Inbox are not self-explaining | WP4 | Fixed (adapted): collapsible page intro with a pointer to the terminal command, a help line per view, empty states, Inbox with time, severity (icon, word and meaning), labelled fields, filter, grouped repeats and an open count on the tab. Not built: separate "?" panels (the help lines and tooltips cover the same text) and severity colours (the host theme's colours are not known to the plugin, so severity is never colour alone); the published glossary is WP5 |
| Docs for #205-#208, #210 | WP5 | Done: USER-GUIDE sections 5 (dashboard views and limits) and 12 (output formats, generated glossary with a staleness test), REFERENCE dashboard routes, install commands under the new repository name, a `docs` link on every bundled module. Not done: `based_on` for the bundled modules (no module has a recorded reuse of another project's code, so naming an upstream would be a claim without a record; `docs/MODULES.md` lists the projects that were studied); the wiki pages, which describe a released version and are refreshed with the release |
| #208 no glossary (label source) | WP2 | Fixed: `hermes_signalbox.labels` with a completeness test; the served route and the published glossary follow in WP3 and WP5 |

## 7. Retro (fill in after phase close)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
