# Trimmer (bundled module, M8)

Shortens long terminal and tool output before it reaches the model. Q&A:
[docs/qa/09-m8-prework.md](../../../../docs/qa/09-m8-prework.md); core contract:
[ADR-0008](../../../../docs/adr/0008-output-transforms.md).

## What it does

For output longer than `min_chars` (4000 characters):

1. Repeated identical consecutive lines keep their first line. Progress-shaped lines (percentages, `n/m`
   counters, transfer rates) also collapse when only their numbers differ; other lines never do, so a changed
   value is not hidden.
2. If more than `max_lines` (200) remain, the first `head` (60) and last `tail` (80) are kept.

The core then **always** puts back lines with errors, warnings, `ERR!`, apt `E:` lines, linter codes, exit
codes (`exit code`, `exited with`, `rc=`), absolute, `~/` and `./` paths, `file:line` references and any line
over 4,000 characters (if more than 2,000 lines qualify, nothing is trimmed), and marks each gap with `[signalbox: N lines omitted]`. The module only
chooses lines; it cannot add or change text. ANSI colour codes and progress-bar redraws are removed.

Measured on the recorded fixtures in `tests/fixtures/output/` with default settings:

| Fixture | Characters in | Out | Saved |
|---|---|---|---|
| `cargo_build.txt` (1500 `[n/m] Compiling` lines, one error) | 59,104 | 493 | 99.2% |
| `npm_install.txt` (700 fetch lines) | 58,772 | 10,136 | 82.8% |
| `pytest_fail.txt` (600 passes, one failure) | 24,722 | 5,809 | 76.5% |
| `pip_install.txt` (300 lines naming site-packages paths, kept on purpose) | 56,021 | 31,902 | 43.1% |

## Turning it on

Activation is manual: grant `hermes.output` (the module reads tool output, which can contain anything a tool
printed) and `ui.panel`, then activate. Terminal output is always eligible; other tools' results only for tools
listed in `tools`. File-writing tools (`write_file`, `patch`, ...) cannot be listed: Hermes keeps only the
first `transform_tool_result` answer, and their results carry Hermes's security-guidance warnings.

A module with `hermes.output` can hide any line that is not must-keep (the marker shows only a count): granting
it is a trust decision.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `report` (calls and characters saved per tool) | yes |
| Action | `preview {text}` | no |
| Panel | `trimmer.status` | |
| Config | `[modules.trimmer]` `min_chars` (4000, 500-1000000), `max_lines` (200, 20-100000), `head` (60), `tail` (80), `tools` ([]) | |

## State and removal

Table `stats` (per tool totals). Removed with the module unless `keep_data`.

## Security review (M8 gate)

Reviewed 2026-11-20 by a fresh subagent with the M8 diff, the threat table and the Hermes v0.23.2 sources.

| Finding | Disposition |
|---|---|
| (high) Must-keep regex backtracked quadratically on long dotted lines, outside any timeout | **Fixed.** Linear patterns; lines over 4,000 characters are kept without scanning; tested on 1 MB lines |
| (high) Carriage-return collapse could delete an error before must-keep ran; normalisation alone changed output | **Fixed.** Overwritten parts with a must-keep match keep the line whole; output changes only when a module trims |
| (high) Huge range spans made rebuild unbounded | **Fixed.** Ranges are coalesced: O(R log R + N) |
| (medium) Must-keep lines over the 2,000 cap were dropped | **Fixed.** Over the cap nothing is trimmed |
| (medium) Exit-code and tool error forms missing (`exited with 2`, `npm ERR!`, apt `E:`) | **Fixed.** Added, with tests |
| (medium) Digit-normalised dedupe hid changed values | **Fixed.** Only progress-shaped lines collapse by shape |
| (medium) First-string-wins could drop Hermes security-guidance warnings | **Fixed.** File-writing tools cannot be trimmed |
| (medium) Per-field timeouts multiplied; hung module slowed every call | **Fixed.** One field per result; three failures pause the module for 5 minutes (audited) |
| (low) Duplicate JSON keys merged on re-encode | **Fixed.** Such results are left alone |
| (low) ANSI removal can join fragments | **Accepted**, documented in ADR-0008 (terminals render the same text) |
| (low) A module can hide non-keyword lines | **Accepted**, documented: granting `hermes.output` is the trust decision |

