# Secrets (M1)

Gives the core secrets broker real backends, tracks age and expiry by name, and rotates generated secrets.
Values stay inside the broker: modules and Hermes see `secret://name` only.

| | |
|---|---|
| Id | `secrets` |
| Phase | M1 |
| Isolation | in-process (bundled) |
| License class | open |

## Capabilities requested

| Capability | Why it is needed | What breaks without it |
|---|---|---|
| `secrets.read` | Required to provide backends to the broker (ADR-0002) | No backends; every `secret://` lookup fails closed |
| `process.spawn` | Runs `security` (macOS), `secret-tool` (Linux) and `bw` (Vaultwarden) | Only the Windows and env backends work |
| `ui.panel` | `secrets.status` panel | No dashboard view; actions still work |

The module starts automatically (`activation = "auto"`) once all three are granted.

## Backends

| Name | Store | Read | Write | Notes |
|---|---|---|---|---|
| `wincred` | Windows Credential Manager, target `signalbox:<name>` | yes | yes | ctypes, no dependency |
| `keychain` | macOS login keychain, service `signalbox`, account `<name>` | yes | no | writing would put the value on a command line |
| `secret-tool` | Secret Service (GNOME Keyring, KWallet), attributes `service=signalbox account=<name>` | yes | yes | value written through stdin |
| `bw` | Vaultwarden or Bitwarden, item name = `<name>`, password field | yes | no | the operator unlocks `bw` and exports `BW_SESSION` |
| `env` | `SIGNALBOX_SECRET_<NAME>` | yes | no | development only; refused unless `allow_env_backend = true` |

A locked backend (bw locked or signed out, keyring error) fails closed: the lookup stops with an error instead
of falling through to the next backend. A backend that does not hold the name passes to the next one.

## Control surface

| Kind | Name | Purpose |
|---|---|---|
| Action (read-only) | `status` | Backends (available, writable) and per-name metadata |
| Action | `rotate {name, backend?}` | Write a fresh random value; never shown |
| Action | `expire {name, date}` | Record an expiry date (`YYYY-MM-DD`) |
| Panel | `secrets.status` | Same data as `status` |
| Config | `[modules.secrets]` | `backends`, `allow_env_backend`, `bw_session_env`, `rotation_length`, `expiry_warning_days` |

Run actions with `hermes-signalbox module action secrets --action rotate --args '{"name": "db.password"}'`, the API,
or `/signalbox module action secrets rotate name=db.password`. The Hermes model tool can run `status` only.

## Events, logs and reports

Log stream `secrets`: backend enabled, rotation, expiry set (names only). Audit: `module.secrets.rotated`,
`module.secrets.expiry_set`, plus the core's `secret.used`, `secret.backend_added`, `process.spawned`. Health
reports available backends and names expiring within `expiry_warning_days`.

## Data

Table `m_secrets__meta` (name, backend, created_at, rotated_at, expires_at). No secret values are stored.
Removal drops the table unless `keep_data`; values in the OS stores and Vaultwarden are never deleted.

## Security notes

Names are checked (`[a-z0-9][a-z0-9._-]`, max 64) before any helper runs; helpers get an argv list, a minimal
environment, stdin from the null device (or the value, for `secret-tool store`), and a timeout; their stderr is
never copied into errors. Rotation values come from `secrets.token_urlsafe`.

## Update and rollback

Bundled; updates with the Signalbox release. Health check: at least one configured backend is available.

## Contract tests

`tests/modules/test_secrets.py` runs `hermes_signalbox.contract.run_contract` on this directory plus unit tests for
each backend and a real Credential Manager round trip on Windows.

## Third-party code

None. Hermes `agent/secret_sources` (MIT) was read as a design reference; nothing copied.

## Security review (M1 gate)

Reviewed 2026-11-19 by a fresh subagent with only the M1 diff and the threat table; every finding was checked
against the code.

| Finding | Disposition |
|---|---|
| (high) On Windows `shutil.which` searches the working directory first, so a planted `bw.cmd` would run and receive `BW_SESSION` | **Fixed.** `hermes_signalbox.process.find_program` refuses relative results and anything in the working directory; used by the process broker, the backends, update control (`git`) and the API (`icacls`) |
| (medium) `rotate` could write to a later backend while an earlier one keeps serving the old value, and silently move a secret off its recorded backend | **Fixed.** Rotation refuses when an earlier available backend holds the name (or cannot be checked), and never leaves the recorded backend implicitly |
| (low) `available()` contract allowed "locked" to fall through | **Fixed (contract).** `available()` means "exists here"; locked backends must raise from `get` |
| (low) Backend provider manifest without `secrets.read` passed validation | **Fixed.** Cross-field rule |
| (low) `run_contract` TOML writer did not validate keys or values | **Fixed.** Keys `[a-z][a-z0-9_]*`; values str, int, bool or lists of those |
| (low) Huge `expiry_warning_days` overflowed | **Fixed.** 0 to 3650 |
| (low) `/signalbox ... x=--5` raised an uncaught error | **Fixed.** Integers parsed with a strict pattern |
| (low) Redaction ran on JSON text, so escaped values could slip through | **Fixed.** Results are redacted as Python values (including dict keys) before serialising |
| Credential buffers are not zeroed in memory | **Accepted.** Python strings are immutable; not achievable in pure Python |

