CREATE TABLE jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id TEXT NOT NULL UNIQUE,
 action TEXT NOT NULL CHECK(action IN ('research','update_check','update_install')),
 status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','expired')),
 created INTEGER NOT NULL,
 expires INTEGER NOT NULL,
 delivered_at INTEGER,
 message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX jobs_status ON jobs(status,expires);
