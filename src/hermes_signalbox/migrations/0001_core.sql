-- 0001: core tables. STRICT tables need SQLite >= 3.37.
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
) STRICT;

CREATE TABLE modules (
  id           TEXT PRIMARY KEY,
  version      TEXT NOT NULL,
  mode         TEXT NOT NULL CHECK (mode IN ('manual', 'auto', 'disabled')),
  state        TEXT NOT NULL,
  installed_at TEXT NOT NULL,
  updated_at   TEXT NOT NULL
) STRICT;

CREATE TABLE grants (
  module_id  TEXT NOT NULL,
  capability TEXT NOT NULL,
  granted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  PRIMARY KEY (module_id, capability)
) STRICT;

CREATE TABLE triggers (
  id             TEXT PRIMARY KEY,
  module_id      TEXT NOT NULL,
  kind           TEXT NOT NULL CHECK (kind IN ('time', 'event', 'usage', 'capacity')),
  spec           TEXT NOT NULL,
  target         TEXT NOT NULL,
  min_interval_s INTEGER NOT NULL DEFAULT 0,
  last_run       TEXT
) STRICT;

CREATE TABLE kv (
  module_id TEXT NOT NULL,
  key       TEXT NOT NULL,
  value     TEXT NOT NULL,
  PRIMARY KEY (module_id, key)
) STRICT;

CREATE TABLE counters (
  module_id TEXT NOT NULL,
  name      TEXT NOT NULL,
  value     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (module_id, name)
) STRICT;
