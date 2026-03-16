CREATE TABLE IF NOT EXISTS review_schedule (
    topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    interval_index INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TIMESTAMP,
    next_review_at TIMESTAMP NOT NULL,
    score_at_last_review REAL,
    PRIMARY KEY (topic, course_id)
);

CREATE INDEX IF NOT EXISTS idx_review_schedule_due ON review_schedule(next_review_at);
