CREATE TABLE IF NOT EXISTS owner_password (
  id INTEGER PRIMARY KEY CHECK(id=1),
  bootstrap_hash TEXT NOT NULL,
  version TEXT NOT NULL,
  salt TEXT NOT NULL,
  digest TEXT NOT NULL,
  iterations INTEGER NOT NULL CHECK(iterations=600000)
);
