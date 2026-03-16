CREATE TABLE IF NOT EXISTS discovered_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    isbn TEXT,
    source TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    course_name TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(title, course_id, source)
);

CREATE INDEX IF NOT EXISTS idx_discovered_refs_course ON discovered_references(course_id);
CREATE INDEX IF NOT EXISTS idx_discovered_refs_isbn ON discovered_references(isbn);
CREATE INDEX IF NOT EXISTS idx_discovered_refs_course_name ON discovered_references(course_name);
