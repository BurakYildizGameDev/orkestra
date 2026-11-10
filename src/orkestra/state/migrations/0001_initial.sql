-- Schema version 1 (Faz 3). Never edit this file; add a new migration instead.

CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, task_id TEXT, kind TEXT, status TEXT,
  provider TEXT, model TEXT, tier INTEGER, attempts INTEGER,
  started_at TEXT, finished_at TEXT, duration_s REAL,
  workspace TEXT, worktree TEXT, applied INTEGER DEFAULT 0,
  tags TEXT,                     -- JSON list
  batch_id TEXT,
  worker_output_tokens INTEGER,  -- savings counter
  envelope_chars INTEGER         -- size of the envelope returned to the chief
);

CREATE TABLE usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, provider TEXT, model TEXT, day TEXT,     -- day = local date YYYY-MM-DD
  prompt_tokens INTEGER, completion_tokens INTEGER, cost_usd REAL,
  requests INTEGER, runs INTEGER, estimated INTEGER, kind TEXT,  -- kind: reservation|actual
  created_at TEXT                -- local ISO time; reservations older than 1 hour are ignored
);

CREATE INDEX usage_provider_day ON usage (provider, day);

CREATE TABLE consents (
  provider TEXT PRIMARY KEY, settings_hash TEXT, granted_at TEXT
);

CREATE TABLE health (
  provider TEXT PRIMARY KEY, consecutive_failures INTEGER,
  open_until TEXT, last_error TEXT
);
