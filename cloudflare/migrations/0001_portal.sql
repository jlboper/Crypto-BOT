CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  csrf TEXT NOT NULL,
  owner_version TEXT NOT NULL,
  expires INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS session_expiry ON sessions(expires);
CREATE TABLE IF NOT EXISTS login_budget (
  id INTEGER PRIMARY KEY CHECK(id=1), window_start INTEGER NOT NULL, attempts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, received_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL CHECK(action IN ('kill','resume')),
  expires INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','applied','expired','superseded')),
  created INTEGER NOT NULL,
  delivered_at INTEGER
);
CREATE INDEX IF NOT EXISTS command_status ON commands(status,expires);
CREATE INDEX IF NOT EXISTS command_retention ON commands(created);
