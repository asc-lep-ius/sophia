CREATE TABLE IF NOT EXISTS transcriptions (
    episode_id TEXT PRIMARY KEY REFERENCES lecture_downloads(episode_id),
    module_id INTEGER NOT NULL,
    language TEXT NOT NULL DEFAULT 'de',
    duration_s REAL,
    segment_count INTEGER,
    srt_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES transcriptions(episode_id),
    segment_index INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transcript_segments_episode ON transcript_segments(episode_id);
CREATE INDEX IF NOT EXISTS idx_transcriptions_status ON transcriptions(status);
