CREATE TABLE IF NOT EXISTS lecture_downloads (
    episode_id TEXT PRIMARY KEY,
    module_id INTEGER NOT NULL,
    series_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    track_url TEXT NOT NULL,
    track_mimetype TEXT NOT NULL,
    file_path TEXT,
    file_size_bytes INTEGER,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lecture_downloads_module ON lecture_downloads(module_id);
CREATE INDEX IF NOT EXISTS idx_lecture_downloads_status ON lecture_downloads(status);
