# Capability process.spawn

> **Type:** capability · **Applies to:** v1.0.0 · **Last checked:** 2026-11-20 · **Status:** draft

**Allows:** Run external programs with a fixed argument list.

**Risk:** high

## How it is enforced

ProcessBroker: no shell, scrubbed environment, output to files with a cap, whole process tree killed on timeout, audited.

Which programs: when the module's manifest lists `capabilities.programs`, only those bare names run (found on PATH; a path in `argv[0]` is refused; on Windows case and `.exe` are ignored). Without a list the grant covers **any program**, and `module show` reports `programs: any` (1.1, H1 B-10). An empty list (`programs = []`) means **no program**. A list may not name a shell or interpreter (`cmd`, `powershell`, `sh`, `python`, `node`, `env` and similar), which would let the module run any code. The bundled modules list theirs: secrets `bw`, `secret-tool`, `security`; scanner its six scanners; offload `claude`, `codex`.

Arguments and environment (1.1): a batch file (`.cmd`, `.bat`) is run by `cmd.exe`, which treats `& | < > ^ % ! " ( )` and line breaks in its arguments as commands, so an argument containing one of them is refused for a batch file. A module may add environment variables for the child, but not ones that choose what runs or what it loads (`PATH`, `PATHEXT`, `COMSPEC`, `GIT_*`, `LD_*`, `DYLD_*`, `PYTHON*`, `NODE_OPTIONS`, `*_COMMAND`, `*_ASKPASS` and similar).

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
