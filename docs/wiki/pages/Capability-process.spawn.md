# Capability process.spawn

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Run external programs with a fixed argument list.

**Risk:** high

## How it is enforced

ProcessBroker: no shell, scrubbed environment, output to files with a cap, whole process tree killed on timeout, audited.

Which programs: when the module's manifest lists `capabilities.programs`, only those bare names run (found on PATH; a path in `argv[0]` is refused; on Windows case and `.exe` are ignored). Without a list the grant covers **any program**, and `module show` reports `programs: any` (1.1, H1 B-10). The bundled modules list theirs: secrets `bw`, `secret-tool`, `security`; scanner its six scanners; offload `claude`, `codex`.

## Requested by

| Module | Required or optional | Used for |
|---|---|---|
| [[Module secrets]] | required | <use> |
| [[Module scanner]] | required | <use> |
| [[Module offload]] | optional | <use> |

## Granting advice

<To write.>

## Related

- [[Capabilities]]

---
**Sources:** [capabilities.py](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/src/switchyard/capabilities.py) · [REFERENCE.md](https://github.com/vicberger-com/hermes-switchyard/blob/v1.0.0/docs/REFERENCE.md)
