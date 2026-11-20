# Pre-work Q&A: M8 token economy

Date: 2026-11-20. Previous phase: M7, tag v0.8.0.

Answer every question. Take the recommended option, mark it **default accepted**, and continue. Only items that
match a stop condition in `AGENTS.md` go to `BLOCKERS.md`.

## 1. Carried forward

| From | What changed or was learned | Effect on this phase |
|---|---|---|
| M6, M7 retros | Text the model reads must not come from a module; modules return codes or choices and the core writes text | Trimming is deletion-only: modules choose lines, the core rebuilds and writes the only new text |
| M4 | Observer payloads are allow-listed metadata | Transforms see output text (that is their job) under a separate capability, `hermes.output` |

## 2. Research record

| Topic | Source (Hermes v0.23.2, 2026-11-20) | Finding |
|---|---|---|
| Terminal output | `tools/terminal_tool_result.py` 147-160 | `transform_terminal_output(command, output, returncode, task_id, env_type, tool_call_id)`; first string wins; fail-open; Hermes's own size limit still applies afterwards |
| Tool results | `model_tools.py` 885-898 | `transform_tool_result(tool_name, args, result, ..., status, error_type, error_message)`; runs after `post_tool_call`, before context; first string wins; fail-open. Results are usually JSON strings |
| Activation | `hermes_cli/plugins_activation.py` 26 | Both are live as soon as registered |
| Compaction engines | `register_context_engine`, `post_compaction` | Replaces Hermes's compressor: high blast radius, needs its own ADR and fixtures. Deferred (question 1) |
| References | ogallotti/rtk-hermes, vincentkoc/tokenjuice, danbiocchi/hermes-vcc-engine, OthmanAdi/planning-with-files | Ideas (dedupe runs, head/tail, keep errors); nothing copied |

## 3. Questions

| # | Question | Options | Recommended and why | Status |
|---|---|---|---|---|
| 1 | Smallest scope? | (a) trimming only; (b) trimming + compaction engine + task-state files | (a). Trimming is measurable and reversible per call; a compaction engine replaces Hermes's compressor and keeps conversation state, so it gets its own phase item and ADR after R1 planning | default accepted |
| 2 | Capabilities | | New `hermes.output` (the module reads tool and terminal output, which may contain secrets the tool printed); `ui.panel`. No `process.spawn`: no external reducers in v1 | default accepted |
| 3 | Reuse, adapt or write? | | Write | default accepted |
| 4 | New dependencies? | | None | default accepted |
| 5 | Security | | Threat table below | default accepted |
| 6 | State; uninstall | | Table `stats` (per tool: calls, characters in and out). Counts kept in memory on the tool path and written on report or stop | default accepted |
| 7 | Control surface | | Read-only `report`; human-only `preview {text}`. Config `min_chars` (4000), `max_lines` (200), `head` (60), `tail` (80), `tools` ([]). Activation manual | default accepted |
| 8 | Which output | | Terminal output always eligible; tool results only for tools the operator lists; JSON results are trimmed field by field and stay valid JSON | default accepted |
| 9 | What is never dropped | | Lines with error words, linter codes, exit codes, absolute, `~/` and `./` paths, and `file:line` references: enforced by the core, not the module | default accepted |
| 10 | Core contract change? | | ADR-0008 | default accepted |
| 11 | Operator input? | | None (activation is manual) | default accepted |

### Threats and tests (question 5)

| Threat | Control | Test |
|---|---|---|
| Module injects text the model reads | Modules return line ranges; the core rebuilds; only core-written omission markers are new | `test_module_cannot_write_text`, `test_bad_modules_fail_open` |
| Errors, exit codes or paths dropped | Core must-keep set, applied after the module's choice | `test_reduction_on_recorded_fixtures_keeps_what_matters`, `test_specific_lines_survive` |
| Broken tool results | JSON results trimmed per string field and re-encoded | `test_hermes_adapter_keeps_json_valid` |
| A failing module breaks tool calls | Fail open, time-bounded, per-module pool | `test_bad_modules_fail_open` |
| Huge output stalls a turn | Inputs over 4 M characters are not processed | same |
| Revocation leaves the transform active | Revoking `hermes.output` deactivates the module | `test_actions_settings_and_capability` |

## 4. Acceptance tests (written before code)

- [x] Reduction measured on recorded fixtures (`tests/fixtures/output/`, default settings, after the review
  fixes: cargo 99.2%, npm 82.8%, pytest 76.5%, pip 43.1% of characters saved; thresholds asserted).
- [x] Errors, exit codes and paths are never dropped.

## 5. Retro (fill in after merge)

| Assumption that was wrong | Correction | Affects |
|---|---|---|
| Regex on tool output is cheap | Quadratic backtracking on one long line can stall a tool call; core-side work needs its own bounds, not just module timeouts | Every core scan of untrusted text |
| Normalising is harmless | Collapsing CR redraws can delete an error; changes must be justified by an actual trim | Output transforms |
| "Similar" lines are noise | Lines differing only in a number can carry the one failure; collapse only proven progress shapes | Trimming heuristics |
| Hooks compose | Hermes keeps the first `transform_tool_result` string; stay out of tools other plugins annotate | Any first-wins Hermes hook |

