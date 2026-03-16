CREATE TABLE IF NOT EXISTS confidence_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    predicted REAL NOT NULL CHECK(predicted BETWEEN 0.0 AND 1.0),
    actual REAL CHECK(actual IS NULL OR actual BETWEEN 0.0 AND 1.0),
    rated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actual_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_confidence_ratings_course ON confidence_ratings(course_id);
CREATE INDEX IF NOT EXISTS idx_confidence_ratings_topic ON confidence_ratings(course_id, topic);
