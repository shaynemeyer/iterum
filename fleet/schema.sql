-- agent.db - the system of record for a fleet.
-- Three contracts that must not be collapsed into one another.
--
-- The connection preamble that belongs with this schema lives in db.connect():
--   PRAGMA journal_mode = WAL;      -- readers do not block writers
--   PRAGMA busy_timeout = 5000;     -- wait for a busy writer, do not fail instantly
--   PRAGMA foreign_keys = ON;       -- off by default; the REFERENCES below need it
--   BEGIN IMMEDIATE;                -- declare the write up front, on every write path

------------------------------------------------------
-- ============ CONTRACT 1: control state ============
-- Mutable. Answers "what is true right now?"

CREATE TABLE IF NOT EXISTS runs (
  run_id     TEXT PRIMARY KEY,
  agent      TEXT NOT NULL,
  task       TEXT NOT NULL,
  status     TEXT NOT NULL CHECK (status IN
               ('running','done','failed','halted','budget_exhausted')),
  session_id TEXT,
  started_at REAL NOT NULL,
  ended_at   REAL,
  cost_usd   REAL NOT NULL DEFAULT 0,
  heartbeat_at REAL                -- set by a live run.py; stops moving when it dies
);

CREATE TABLE IF NOT EXISTS steps (
  run_id     TEXT NOT NULL REFERENCES runs(run_id),
  seq        INTEGER NOT NULL,
  intent     TEXT NOT NULL,
  status     TEXT NOT NULL CHECK (status IN
               ('proposed','committed','failed','skipped')),
  idem_key   TEXT UNIQUE,          -- not used yet
  receipt    TEXT,                 -- not used yet
  started_at REAL NOT NULL,
  ended_at   REAL,
  PRIMARY KEY (run_id, seq)
);

-------------------------------------
-- ============ receipts ============
CREATE TABLE IF NOT EXISTS receipts (
  idem_key    TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL,
  seq         INTEGER,
  params_hash TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('in_flight','ok','failed')),
  body        TEXT,
  created_at  REAL NOT NULL,
  settled_at  REAL
);

---------------------------------------------------------
-- ============ CONTRACT 2: the event ledger ============
-- Append-only. Answers "what happened, in what order?"

CREATE TABLE IF NOT EXISTS events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid      TEXT NOT NULL UNIQUE,   -- uuid7, identical on every device
  device   TEXT NOT NULL,          -- ITERUM_DEVICE of the device that wrote it
  run_id   TEXT NOT NULL,
  seq      INTEGER,
  ts       REAL NOT NULL,
  stage    TEXT NOT NULL,
  kind     TEXT NOT NULL,
  payload  TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS events_by_run ON events(run_id, event_id);

CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;

CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;

-- ============ CONTRACT 3: derived knowledge ============
-- Rebuildable. Answers "what have we concluded, and from what?"
-- Named `knowledge`, not `claims`. The word `claims` is taken by the work
-- registry below, and the collision is worth avoiding in your own head.

CREATE TABLE IF NOT EXISTS knowledge (
  knowledge_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  subject       TEXT NOT NULL,
  claim         TEXT NOT NULL,
  source_event  INTEGER REFERENCES events(event_id),
  scope         TEXT NOT NULL DEFAULT 'project',
  valid_from    REAL NOT NULL,
  valid_to      REAL,
  superseded_by INTEGER REFERENCES knowledge(knowledge_id)
);

-- ============ claims, leases and fences ============
CREATE TABLE IF NOT EXISTS claims (
  resource   TEXT PRIMARY KEY,
  run_id     TEXT NOT NULL,
  agent      TEXT NOT NULL,
  fence      INTEGER NOT NULL,
  granted_at REAL NOT NULL,
  expires_at REAL NOT NULL
);

-- `fences` rows are never deleted, even when the claim is released. Delete one
-- and you have silently downgraded the guarantee back to a bare lease.
CREATE TABLE IF NOT EXISTS fences (
  resource TEXT PRIMARY KEY,
  high     INTEGER NOT NULL
);

-- ============ the work queue ============
CREATE TABLE IF NOT EXISTS tasks (
  task_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  kind         TEXT NOT NULL,
  payload      TEXT NOT NULL DEFAULT '{}',
  status       TEXT NOT NULL CHECK (status IN
                 ('ready','in_progress','done','dead_letter','halted')),
  depends_on   INTEGER REFERENCES tasks(task_id),
  attempts     INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  reason       TEXT,
  deadline     REAL,
  created_at   REAL NOT NULL,
  ended_at     REAL
);

CREATE TABLE IF NOT EXISTS leases (
  task_id      INTEGER PRIMARY KEY REFERENCES tasks(task_id),
  worker       TEXT NOT NULL,
  granted_at   REAL NOT NULL,
  expires_at   REAL NOT NULL,
  heartbeat_at REAL NOT NULL
);

-- ============ budgets ============
-- `scope` is a string so `fleet`, `agent:worker-3` and `run:abc123` all meter
-- through one table.
CREATE TABLE IF NOT EXISTS budgets (
  scope        TEXT PRIMARY KEY,
  limit_usd    REAL NOT NULL,
  spent_usd    REAL NOT NULL DEFAULT 0,
  window_start REAL NOT NULL
);

-- ============ the eval suite ============
CREATE TABLE IF NOT EXISTS evals (
  eval_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  source_run TEXT,
  kind       TEXT NOT NULL CHECK (kind IN ('regression','capability')),
  expect     TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_results (
  eval_id   INTEGER NOT NULL REFERENCES evals(eval_id),
  suite_run TEXT NOT NULL,
  passed    INTEGER NOT NULL,
  detail    TEXT,
  ts        REAL NOT NULL,
  PRIMARY KEY (eval_id, suite_run)
);

-- ============ approvals ============
CREATE TABLE IF NOT EXISTS approvals (
  approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      TEXT NOT NULL,
  seq         INTEGER,
  action      TEXT NOT NULL,
  fingerprint TEXT NOT NULL UNIQUE,
  decision    TEXT CHECK (decision IN ('pending','approved','denied')),
  decided_by  TEXT,
  requested_at REAL NOT NULL,
  decided_at  REAL
);
