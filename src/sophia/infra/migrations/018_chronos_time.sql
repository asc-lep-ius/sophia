CREATE TABLE IF NOT EXISTS time_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deadline_id TEXT NOT NULL,
    hours REAL NOT NULL CHECK(hours > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    note TEXT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS active_timers (
    deadline_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deadline_reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deadline_id TEXT NOT NULL,
    predicted_hours REAL,
    actual_hours REAL,
    reflection_text TEXT,
    reflected_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_time_entries_deadline ON time_entries(deadline_id);
