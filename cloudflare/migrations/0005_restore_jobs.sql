CREATE TABLE jobs_restore_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id TEXT NOT NULL UNIQUE,
 action TEXT NOT NULL CHECK(action IN ('research','update_check','update_install','update_restore')),
 status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','expired')),
 created INTEGER NOT NULL,
 expires INTEGER NOT NULL,
 delivered_at INTEGER,
 message TEXT NOT NULL DEFAULT '',
 release_id TEXT
);
INSERT INTO jobs_restore_new(id,request_id,action,status,created,expires,delivered_at,message,release_id)
 SELECT id,request_id,action,status,created,expires,delivered_at,message,release_id FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_restore_new RENAME TO jobs;
CREATE INDEX jobs_status ON jobs(status,expires);
