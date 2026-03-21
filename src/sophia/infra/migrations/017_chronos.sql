CREATE TABLE IF NOT EXISTS deadline_cache (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    course_name TEXT NOT NULL DEFAULT '',
    deadline_type TEXT NOT NULL,
    due_at TEXT NOT NULL,
    grade_weight REAL,
    submission_status TEXT,
    url TEXT,
    extra TEXT DEFAULT '{}',
    synced_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_deadline_cache_course ON deadline_cache(course_id);
CREATE INDEX IF NOT EXISTS idx_deadline_cache_due ON deadline_cache(due_at);

CREATE TABLE IF NOT EXISTS effort_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deadline_id TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    predicted_hours REAL NOT NULL CHECK(predicted_hours > 0),
    breakdown TEXT,
    implementation_intention TEXT,
    scaffold_level TEXT NOT NULL DEFAULT 'full',
    estimated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_effort_estimates_deadline ON effort_estimates(deadline_id);
CREATE INDEX IF NOT EXISTS idx_effort_estimates_course ON effort_estimates(course_id);
