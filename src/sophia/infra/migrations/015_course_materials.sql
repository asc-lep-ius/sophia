CREATE TABLE IF NOT EXISTS course_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    module_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    url TEXT,
    mimetype TEXT,
    file_size_bytes INTEGER,
    pdf_text TEXT,
    chunk_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_course_materials_url
    ON course_materials(course_id, url);

ALTER TABLE lecture_downloads ADD COLUMN lecture_number INTEGER;
