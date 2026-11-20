# ADR-0002: Module-provided secret backends and module actions

Status: accepted, 2026-11-19. Phase: M1. Q&A: [02-m1-prework.md](../qa/02-m1-prework.md) question 10.

## Context

`DESIGN.md` section 3 says secret backends are modules and the core defines the interface only. M0 shipped the
broker (`SecretsBroker`) with backends passed in at construction; no module could add one. M0 also gave modules
no way to expose operations: the core operation table is fixed, so a module could offer only panels. M1 needs
both (backends; `rotate` and `expire`), and every later module needs operations.

## Decision

1. **Secret backends.** Manifest field `contributes.secret_backends` (list of backend names). A module adds a
   backend with `ctx.provide_secret_backend(backend)`. The core accepts it only if all hold:
   the module is in-process and was loaded from a trusted root; it is granted `secrets.read`; `backend.name` is
   declared in `contributes.secret_backends`; no other module provides that name. Backends are removed when the
   module stops. Order of lookup follows the core config `secrets.backend_order`, then registration order.
   Backends may implement `set(name, value)` to be writable. A T2 module can never provide a backend, because
   a backend sees every secret value it serves.
2. **Module actions.** A module registers `ctx.register_action(name, handler, params=..., read_only=False)` for
   a name declared in `contributes.commands`. `params` maps names to `bool | int | str`; the core validates
   arguments before calling. One new core operation, `module action {id, action, args}`, runs it through the
   same table that drives the CLI, API and Hermes adapter. Results must be JSON-serialisable and pass through
   the redactor; failures return the core's error messages only. The Hermes model tool may run an action only
   if it is `read_only`. Actions require the hosting process. Each call is audited (`module.action`, names
   only; arguments are not recorded).

## Consequences

- The core stays interface-only for secrets; M1 can ship OS-store and Vaultwarden backends as a module.
- Manifest schema 1 gains an optional field; existing manifests stay valid.
- Later modules get a uniform, policy-checked control surface instead of growing the core operation table.
