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
| `wincred` | Windows Credential Manager, target `switchyard:<name>` | yes | yes | ctypes, no dependency |
| `keychain` | macOS login keychain, service `switchyard`, account `<name>` | yes | no | writing would put the value on a command line |
| `secret-tool` | Secret Service (GNOME Keyring, KWallet), attributes `service=switchyard account=<name>` | yes | yes | value written through stdin |
| `bw` | Vaultwarden or Bitwarden, item name = `<name>`, password field | yes | no | the operator unlocks `bw` and exports `BW_SESSION` |
| `env` | `SWITCHYARD_SECRET_<NAME>` | yes | no | development only; refused unless `allow_env_backend = true` |

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

Run actions with `switchyard module action secrets --action rotate --args '{"name": "db.password"}'`, the API,
or `/switchyard module action secrets rotate name=db.password`. The Hermes model tool can run `status` only.

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

Bundled; updates with the Switchyard release. Health check: at least one configured backend is available.

## Contract tests

`tests/modules/test_secrets.py` runs `switchyard.contract.run_contract` on this directory plus unit tests for
each backend and a real Credential Manager round trip on Windows.

## Third-party code

None. Hermes `agent/secret_sources` (MIT) was read as a design reference; nothing copied.
