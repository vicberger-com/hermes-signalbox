# Trimmer (bundled module, M8)

Shortens long terminal and tool output before it reaches the model. Q&A:
[docs/qa/09-m8-prework.md](../../../../docs/qa/09-m8-prework.md); core contract:
[ADR-0008](../../../../docs/adr/0008-output-transforms.md).

## What it does

For output longer than `min_chars` (4000 characters):

1. Repeated consecutive lines (also when only numbers differ, such as progress counters) keep their first line.
2. If more than `max_lines` (200) remain, the first `head` (60) and last `tail` (80) are kept.

The core then **always** puts back lines with errors, warnings, linter codes, exit codes, absolute, `~/` and
`./` paths, and `file:line` references, and marks each gap with `[switchyard: N lines omitted]`. The module only
chooses lines; it cannot add or change text. ANSI colour codes and progress-bar redraws are removed.

Measured on the recorded fixtures in `tests/fixtures/output/` with default settings:

| Fixture | Characters in | Out | Saved |
|---|---|---|---|
| `cargo_build.txt` (1500 compile lines, one error) | 59,104 | 493 | 99.2% |
| `npm_install.txt` (700 fetch lines) | 58,772 | 247 | 99.6% |
| `pytest_fail.txt` (600 passes, one failure) | 24,722 | 743 | 97.0% |
| `pip_install.txt` (300 lines naming site-packages paths, kept on purpose) | 56,021 | 32,013 | 42.9% |

## Turning it on

Activation is manual: grant `hermes.output` (the module reads tool output, which can contain anything a tool
printed) and `ui.panel`, then activate. Terminal output is always eligible; other tools' results only for tools
listed in `tools`.

## Control surface

| Kind | Name | Model may run |
|---|---|---|
| Action | `report` (calls and characters saved per tool) | yes |
| Action | `preview {text}` | no |
| Panel | `trimmer.status` | |
| Config | `[modules.trimmer]` `min_chars` (4000, 500-1000000), `max_lines` (200, 20-100000), `head` (60), `tail` (80), `tools` ([]) | |

## State and removal

Table `stats` (per tool totals). Removed with the module unless `keep_data`.
