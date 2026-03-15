CREATE TABLE IF NOT EXISTS topic_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'lecture' CHECK(source IN ('lecture', 'quiz', 'manual')),
    frequency INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(topic, course_id, source)
);

CREATE TABLE IF NOT EXISTS topic_lecture_links (
    topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    chunk_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (topic, course_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_topic_mappings_course ON topic_mappings(course_id);
CREATE INDEX IF NOT EXISTS idx_topic_lecture_links_course ON topic_lecture_links(course_id);
CREATE INDEX IF NOT EXISTS idx_topic_lecture_links_episode ON topic_lecture_links(episode_id);
