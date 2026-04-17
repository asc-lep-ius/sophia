CREATE TABLE IF NOT EXISTS topic_reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_topic TEXT NOT NULL,
    moodle_topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    similarity REAL NOT NULL,
    reconciled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(manual_topic, course_id)
);
