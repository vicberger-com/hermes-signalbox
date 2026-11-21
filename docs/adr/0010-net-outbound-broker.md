# ADR-0010: The `net.outbound` broker

Status: accepted, 2026-11-20. Phase: M11. Q&A: [12-m11-prework.md](../qa/12-m11-prework.md) question 9.

## Decision

`ctx.net.request(method, url, json=, headers=, timeout=)` for modules granted `net.outbound`:

1. Only `http`/`https`, no credentials in the URL, methods GET/POST/PUT/PATCH/DELETE.
2. The host must be in the manifest's `net_hosts`: `host:port` exactly, or a bare `host` for any port (a bare
   entry is a deliberate widening: list ports when the module can know them).
3. No redirects (a redirect could leave the list); environment proxies ignored.
4. Request body at most 1 MB, response read at most 4 MB (`truncated` flag), timeout at most 120 s as a total
   deadline; a response shorter than its `Content-Length` is a failure; malformed URLs are refused.
5. Audit `net.request` with host, method and status or error class; never paths, headers or bodies.
6. Module headers with CR/LF are dropped, and so is a module-set `Host` header: the request goes to the host
   the allow-list checked (1.1).

## Consequences

- Remote hosts chosen by the operator at run time are not possible yet; a later ADR can add an operator-approved
  host list.
