CREATE TABLE paper_controls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL CHECK(action IN ('risk_profile','paper_close')),
  payload TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','completed','failed','expired')),
  message TEXT NOT NULL DEFAULT '',
  created INTEGER NOT NULL,
  expires INTEGER NOT NULL,
  delivered_at INTEGER
);
CREATE INDEX paper_controls_status ON paper_controls(status,expires);
CREATE INDEX paper_controls_retention ON paper_controls(created);
