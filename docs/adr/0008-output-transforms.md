# ADR-0008: Deletion-only output transforms

Status: accepted, 2026-11-20. Phase: M8. Q&A: [09-m8-prework.md](../qa/09-m8-prework.md) question 10.

## Decision

1. New capability `hermes.output`: a module may read Hermes terminal output and tool results in order to shorten
   them. It registers `ctx.hermes_transform(kind, fn)` (`terminal_output` or `tool_result`, declared as
   `transform:<kind>` in `contributes.hooks`).
2. `fn(lines, meta)` returns the `[start, end)` line ranges to keep, or `None`. `meta` is allow-listed metadata
   (tool name, return code, status). The core (`switchyard.trim`) normalises the text first (ANSI sequences
   removed, carriage-return redraws collapsed), rebuilds the output from the original lines, always adds
   must-keep lines (errors, linter codes, exit codes, paths, `file:line`), and writes the only new text:
   `[switchyard: N lines omitted]`. Invalid answers, errors and timeouts leave the output unchanged.
3. The adapter registers Hermes's `transform_terminal_output` and `transform_tool_result`. JSON tool results are
   trimmed per long string field and re-encoded, so they stay valid JSON.

## Consequences

- A module cannot add, reword or reorder output, so it cannot inject instructions through tool results.
- Compaction engines (`register_context_engine`) are out of scope until a separate ADR.
