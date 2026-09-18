ALTER TABLE jobs ADD COLUMN release_id TEXT;
CREATE TABLE bot_releases (
 sequence INTEGER PRIMARY KEY,
 release_id TEXT NOT NULL UNIQUE,
 commit_sha TEXT NOT NULL,
 envelope TEXT NOT NULL,
 created INTEGER NOT NULL
);
