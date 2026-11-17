-- Schema version 5 (Faz 13k, Mimari §6.2, D-094): every used-up quota with how much was used
-- since its window began, so a limit nobody wrote down can be learned. Never edit this file;
-- add a new migration instead.

CREATE TABLE quota_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  at TEXT NOT NULL,        -- local ISO time of the quota error
  since TEXT NOT NULL,     -- start of the window: local midnight, or when the last pause ended
  resumes_at TEXT,         -- when the pause ends
  runs INTEGER,            -- usage between since and at (actual rows only)
  requests INTEGER,
  tokens INTEGER
);

CREATE INDEX quota_events_provider ON quota_events (provider, at);
