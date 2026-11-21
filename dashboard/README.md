# Switchyard dashboard tab

Hermes loads this folder as the Switchyard dashboard plugin (`manifest.json`).

- `dist/index.js` and `dist/style.css` are the **source**, written by hand. There is no build step, bundler or
  package file. Edit them directly. The JS uses only the Hermes plugin SDK (`window.__HERMES_PLUGIN_SDK__`) and
  calls only this plugin's own `/api/plugins/switchyard/` routes.
- `plugin_api.py` is the backend: a fixed list of operations proxied to Switchyard's loopback control API
  (ADR-0009). It runs inside Hermes, which provides FastAPI. It is covered by ruff, mypy, bandit and
  `tests/integration/test_dashboard_api.py` (real FastAPI, in the `hermes-integration` CI job).
- Writes (activate or deactivate a module, ack inbox items) refuse a request the browser marks as sent by
  another page (`Sec-Fetch-Site`), on top of Hermes's own dashboard auth (H1 C-18).
