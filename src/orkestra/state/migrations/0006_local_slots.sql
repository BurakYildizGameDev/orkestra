-- Schema version 6 (Faz 13l, Mimari §12, D-096): requests in flight to local models across
-- all Orkestra processes on this machine, so a local provider's ``concurrency`` holds even
-- when a batch and ``orkestra exec`` run at once. Never edit this file; add a new migration.

CREATE TABLE local_slots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  pid INTEGER NOT NULL,     -- the holder; with created, so a reused pid is not the holder
  created REAL,
  acquired_at TEXT          -- local ISO time
);

CREATE INDEX local_slots_provider ON local_slots (provider);
