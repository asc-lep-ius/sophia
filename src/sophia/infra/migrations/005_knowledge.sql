CREATE TABLE IF NOT EXISTS knowledge_index (
    episode_id TEXT PRIMARY KEY REFERENCES transcriptions(episode_id),
    module_id INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    indexed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_knowledge_index_status ON knowledge_index(status);
