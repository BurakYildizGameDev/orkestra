-- Schema version 3 (Faz 12a, Mimari §6/§21, D-072): the night queue and the lock that lets
-- only one ``queue run`` work at a time. Never edit this file; add a new migration instead.

CREATE TABLE queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL,      -- absolute path of the task or batch file
  kind TEXT NOT NULL,      -- task | batch
  profile TEXT,            -- --profile at add time; NULL: queue.default_profile
  status TEXT NOT NULL,    -- pending | running | done | failed | removed
  added_at TEXT,
  started_at TEXT,
  finished_at TEXT,
  result_ref TEXT,         -- run_id (task) or batch_id (batch)
  workdir TEXT NOT NULL,   -- where it was added: relative paths and the project config
  file_hash TEXT,          -- sha256 of the file at add time
  note TEXT                -- why it failed or was skipped
);

CREATE INDEX queue_status ON queue (status, id);

CREATE TABLE queue_lock (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  pid INTEGER NOT NULL,
  created REAL,            -- the owner's process start time: a reused pid is not the owner
  started_at TEXT
);
