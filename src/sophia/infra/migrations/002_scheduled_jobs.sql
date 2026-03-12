CREATE TABLE IF NOT EXISTS scheduled_jobs (
    job_id     TEXT PRIMARY KEY,
    command    TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    description TEXT NOT NULL DEFAULT ''
);
