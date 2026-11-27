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

- [x] After the rename, `git grep -i switchyard` matches only the allow-list (CHANGELOG history, migration code and its tests, the deprecation shim, ADR-0015, earlier Q&A files). *Evidence:* `test_h5_rename.py::test_h5_the_old_name_survives_only_where_the_upgrade_needs_it`. The check existed since the rename but no test called it until this change; wiring it up found no stray use, only upgrade notes, which are now listed line by line.
- [x] A v1.0.3 data dir is copied on first load of 1.1.0, the audit chain verifies in the copy, `core.migrated` is recorded, the old dir is byte-identical afterwards; a locked old dir is refused with no partial copy. *Evidence:* `test_h5_rename.py`: `..._hermes_data_dir_is_copied_on_first_start`, `..._migration_runs_once`, `..._old_dir_in_use_is_refused_and_nothing_is_written`, `..._tampered_old_audit_is_refused`. These build the old directory inside the test; a directory written by a real v1.0.3 install is exercised only by the upgrade rehearsal below.
- [x] `SWITCHYARD_DATA_DIR` still works in 1.1.x with a deprecation warning; `SIGNALBOX_DATA_DIR` wins when both are set. *Evidence:* `test_h5_rename.py`: `..._old_data_dir_variable_still_works_with_a_warning`, `..._new_data_dir_variable_wins_without_a_warning`.
- [x] Every slash verb returns readable Markdown by default with a summary line; `json=true` returns the previous payload unchanged; model tool output and CLI `--json` are unchanged. *Evidence:* `test_h5_labels.py`: `..._slash_reply_is_markdown_and_json_true_is_the_old_payload`, `..._model_tool_output_is_unchanged`, `..._cli_text_uses_the_formatter_and_json_flag_is_unchanged`, `..._unknown_results_never_fall_back_to_json`.
- [x] Every capability, status, mode, severity and listed audit action has a label (test fails on a missing one). *Evidence:* `test_h5_labels.py`: `..._every_capability_status_mode_and_severity_has_a_label`, `..._every_listed_core_audit_action_has_a_label`.
- [x] Each report kind has a documented purpose and a deterministic `summary`, fixed by tests on known fixtures (healthy, nothing granted, a failed module, a tampered audit log). *Evidence:* `test_h5_labels.py`: `..._every_report_kind_has_a_purpose_and_a_summary`, `..._health_summary_healthy_nothing_granted_and_failed`, `..._security_summary_intact_and_tampered`; purposes in REFERENCE.
- [x] Modules view: description, version, source and update state on every row; a module with missing grants has a disabled button with the reason and the grant command; a refused action shows the core's message on the row; mode is settable, audited `module.mode_changed` with `actor=api`, and refused cross-site. *Evidence:* `test_h5_module_details.py::..._dashboard_rows_carry_description_version_source_and_update`; `test_h5_dashboard_view.py`: `..._a_module_that_lacks_grants_has_a_disabled_button_with_the_reason_and_command`, `..._a_refused_action_shows_the_cores_message_on_the_row`; `test_h5_dashboard_modules.py`: `..._mode_is_set_from_the_dashboard_and_audited_as_the_dashboard`, `..._mode_route_sits_behind_the_write_guard_and_before_the_generic_route`.
- [x] Manifest links: only `https://` accepted by the schema; rendered escaped, with `rel="noopener noreferrer"` and the host shown (hostile-manifest test). *Evidence:* `test_h5_module_details.py::..._a_link_that_is_not_plain_https_fails_the_manifest`; `test_h5_dashboard_view.py::..._only_https_links_are_rendered_with_the_host_and_safe_attributes`.
- [x] With `updates` stopped, the dashboard shows "Not checked" and no fetch happens from the dashboard backend. *Evidence:* `test_h5_module_details.py::..._show_for_a_git_module_never_fetches_and_reports_not_checked`.
- [ ] Reports view: no fixed-height inner scroll box; summary first; no raw JSON unless expanded; Refresh shows a loading state and an "Updated" time on every click and is disabled while loading. *Status:* Partly shown by tests (`test_h5_dashboard_views.py`: summary first, raw JSON collapsed, no clipped box, the Refresh button's working and idle states). Not shown: that a real click returns to idle and moves the "Updated" time, because the test stand-in runs no page loads. Open until seen in a running dashboard.
- [x] Inbox view: time shown, Open/Acknowledged/All filter, repeats grouped, no raw `key=value`, open count on the tab. *Evidence:* `test_h5_dashboard_views.py`: `..._inbox_shows_time_severity_labelled_fields_and_grouped_repeats`, `..._inbox_filter_and_acknowledge_send_the_right_requests`, `..._the_page_explains_itself_and_the_inbox_tab_counts_open_notices`.
- [ ] Keyboard-only and screen-reader pass on all three views (tooltips open on focus and close on Esc). *Status:* Only the wiring is tested (focusable terms, `aria-describedby`, Esc). No pass with a keyboard and a screen reader has been made. Open.
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
| Q-SY-H5-CLOSE-1 (1), (2): `module list` too wide for a terminal; chat rejected `--key value` | after WP5 | Fixed (operator decision 2026-11-26): text tables wider than the terminal are written as one block per row; the chat command reads `--key value`, `--key=value` and `--json` as their `key=value` forms |
| #208 no glossary (label source) | WP2 | Fixed: `hermes_signalbox.labels` with a completeness test; the served route and the published glossary follow in WP3 and WP5 |

| #221 item 2: an `auto` module missing a permission was skipped silently | after WP5 | Fixed in #232 (operator decision 2026-11-26): a start-up notice in the Hermes log, or on stderr for `serve`, names each module, what it needs and the grant command. Item 4 (first-run prompt) stays open on #221 |

## 7. Retro (fill in after phase close)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| A page of commands written from memory is close enough | QUICKSTART and TROUBLESHOOTING showed commands that do not exist and a grant line that gave one permission out of several. Every command in a user-facing page is now parsed by a test (`tests/test_repo_review_docs.py`) | Every later docs change; extend the test to USER-GUIDE and the wiki |
| argparse refuses a repeated option | It keeps the last value silently. Options that take a value now refuse a second use | Any new option |
| Moving from JSON to readable text changes only the look | JSON escaped whatever a module wrote; Markdown and terminal text act on it. The formatter now neutralises module-written text (review R-1) | Any new human-facing surface: decide where untrusted text is neutralised before building it |
| A helper in a test file is a test | The rename guard existed and nothing called it until #230 | Acceptance ticks name the test function that was run |
| The phase-end review can always be delegated | The host's worker policy refused the three reviewers; the review was a self-review with executed probes for one area only | Before the next phase: settle how independent reviewers run (Q-SY-H5-REPO-1) |
| A self-review is a review | Three independent reviewers found eight more things, two of them gaps in the self-review's own fixes (section 9). A phase-end review is done by reviewers who did not write the code, and its fixes are re-checked by someone else | Every phase: arrange the reviewers before the review is due |
| A module that registers a panel has a panel the operator can see | All twelve registered one; the page displayed none (ADR-0016). "Has" in a definition of done means observed on the surface | H6; pre-work question 13 |
| The local suite is the same check as CI | CI also enforces the per-platform skip allow-list; a new POSIX-only test failed Windows CI with every test passing | Add a skip to the allow-list in the same change as the test |
| Dashboard code tested under Node with stand-ins shows how the page behaves | The stand-in does not run effects or re-render, so load timing and appearance are unverified until a person looks | The operator's usability review stays a release gate |

## 8. Phase-end security review (2026-11-26)

Scope: `git diff v1.0.3..HEAD` for `src/`, `dashboard/` and the workflows. Method: the author read the changed
files in three areas (dashboard and control surfaces; rename and data copy; human output and chat parsing)
and ran probes for the output area: hostile text through `present.render` in both styles, 5,000 rows and a
1 MB value for timing, unexpected payload shapes. The dashboard and data-copy areas were read, not probed by
execution. **No independent reviewer took part**: the three delegated reviews this project normally runs
were refused by the host's worker policy, so this is a self-review and weaker than earlier phases.

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| R-1 | Medium | The human formatter printed module-written text as it came: Markdown structure (headings, images that fetch a remote address, links, fences) in chat replies that 1.0.x returned as JSON, and escape sequences at a terminal | Fixed: `present._safe` on every result and summary; `tests/core/test_h5_review.py::test_h5_r1_*` |
| R-2 | Low | `present.render` raised `AttributeError` on a list without records for `module list` and `audit tail` | Fixed: such a list takes the generic path; `test_h5_r2_*` |
| R-3 | Low | The first-start data copy followed symbolic links and junctions out of the old directory | Fixed: refused with the link named; `test_h5_r3_*` |
| R-4 | Low | At a terminal a module's text keeps its line breaks, so it can add lines that look like other fields (true in 1.0.x as well) | Accepted, documented: scripts read `--json`, which escapes them |
| R-5 | Info | A bare `https://` address in module text is still made clickable by Markdown renderers; it shows its real target | Accepted |

Read and found sound: the dashboard profile's allow-list is enforced in the core's server, the mode route
checks the mode in both layers, manifest links pass one strict `https` pattern in the schema and in the page,
the page builds elements without HTML strings, module ids and capability names cannot carry shell or
Markdown characters into the suggested commands, and the copied state holds no absolute path into the old
directory.

## 9. Independent re-review (2026-11-27)

The review in section 8 was a self-review: the host refused the three delegated reviewers. The operator
asked for it to be repeated independently before the tag. Three fresh sessions with file-reading tools only
and no knowledge of the work each reviewed one area of the diff `v1.0.3..d58c82d` (dashboard and control
surface; first-start copy and core; readable output) and were told to check the fixes R-1 to R-3 instead of
trusting them. They read code and ran nothing; every finding below was reproduced by a test or a probe
before it was accepted.

| ID | Finding | Disposition |
|---|---|---|
| R-4 | R-1 was incomplete: `_`/`~` emphasis, line-start constructs, bare addresses as links in chat replies | Fixed |
| R-5 | `RecursionError` in the formatter on deeply nested data | Fixed (cut off at 32 levels) |
| R-6 | stderr failure line unfiltered; a subprocess module chose its error type name; a time out of range broke `audit tail` text | Fixed |
| R-7 | First-start copy: source directory itself a link; copy repeated when the new state was lost; damaged `state.db` copied; OS error as a traceback; permission bits kept | Fixed |
| R-8 | `--data-dir`, `--port` repeated: last value won | Fixed |
| R-9 | Dashboard text not filtered for control and format characters | Fixed |
| R-10 | Inbox notice could name another module as its source | Fixed |
| R-11 | Start-mode route: no body limit or content-type check; list-valued id dropped the connection | Fixed |
| A-1 | Hermes dashboard serves its session token to any loopback client; Signalbox's dashboard routes sit behind it | Not ours to fix. In SECURITY.md "Known limits". Reporting it to Hermes is the operator's decision |
| B-3, B-4 | The copy imports `config.toml` and `modules/` from the old directory | Accepted: same trust as the new directory; in SECURITY.md |
| C-7 | The untrusted-data note on tool results is advisory | Unchanged since 1.0; in SECURITY.md |
| C-4 | Look-alike characters are not normalised | Accepted: normalising would damage ordinary non-English text |
| A-4, A-6, B-6, B-7, B-12 | Audit noise from inbox reads and one actor for two API profiles; "Refused" shown for an unknown outcome; audit head not compared before the copy is committed; legacy secret names used without saying so; whether a migrated grant can cover a wider scope | Deferred to the next phase, in the follow-up issue |

Claims that did not reproduce: `>` is escaped; 100,000 rows and a 10 MB string render in under a second.

What this review still is not: the reviewers are fresh sessions of the same model family as the author, and
none of them executed the code. An external review remains open (SECURITY.md).

