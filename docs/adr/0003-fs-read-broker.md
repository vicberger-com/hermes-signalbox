# ADR-0003: File-read broker (`ctx.fs`)

Status: accepted, 2026-11-19. Phase: M2. Q&A: [03-m2-prework.md](../qa/03-m2-prework.md) question 10.

## Context

`fs.read` is in the capability vocabulary but M0 shipped no broker for it. M2 reads catalog files (the Hermes
models.dev cache, operator-supplied JSON); M5 and M10 will read skill and scan targets.

## Decision

`ctx.fs` (needs `fs.read`) offers `read_text(path, *, max_bytes)` and `read_json(path, *, max_bytes)`:

- the path must be absolute and local: on Windows it must start with a drive letter (no UNC paths, which
  would contact a remote host and send NTLM credentials; no `\\.\` or `\\?\` device paths or device names).
  The grant is checked before any file-system call. The file is opened (non-blocking on POSIX) and `fstat`
  on the handle must show a regular file;
- the file size is checked against `max_bytes` (default 1 MiB, ceiling 32 MiB) before reading, and the read
  itself is bounded;
- text is UTF-8; JSON is screened on the text before parsing (depth 64, at most 1 000 000 values);
- each read is audited as `fs.read` with the resolved path and byte count, and each refusal after the grant
  as `fs.read_failed` with a reason; never the content.

No path allow-list in the manifest yet: the grant is the decision, the audit is the record. A per-module
allow-list can tighten this later without changing the call.

## Consequences

- Modules stop needing ad-hoc `open()` calls for reviewed inputs, and every read leaves a record.
- Write access (`fs.write`) remains unbrokered until a phase needs it.
