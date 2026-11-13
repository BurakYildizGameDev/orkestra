-- Schema version 2 (Faz 10a): one row per chief handoff. Never edit this file; add a new
-- migration instead. Faz 10a only creates the table; ``handoff to`` (Faz 10b) writes rows.

CREATE TABLE handoffs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_chief TEXT,
  to_chief TEXT,
  at TEXT,             -- local ISO time of the handoff
  "commit" TEXT,       -- HEAD the previous chief left behind
  brief_path TEXT      -- where the brief was written (NULL in arg/stdin mode)
);

CREATE INDEX handoffs_at ON handoffs (at);
