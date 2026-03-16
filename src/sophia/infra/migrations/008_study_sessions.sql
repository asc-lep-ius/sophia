CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    pre_test_score REAL CHECK(pre_test_score IS NULL OR pre_test_score BETWEEN 0.0 AND 1.0),
    post_test_score REAL CHECK(post_test_score IS NULL OR post_test_score BETWEEN 0.0 AND 1.0),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_study_sessions_course ON study_sessions(course_id);
CREATE INDEX IF NOT EXISTS idx_study_sessions_topic ON study_sessions(course_id, topic);
