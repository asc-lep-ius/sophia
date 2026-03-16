CREATE TABLE IF NOT EXISTS student_flashcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'study' CHECK(source IN ('study', 'lecture', 'manual')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_flashcards_course ON student_flashcards(course_id);
CREATE INDEX IF NOT EXISTS idx_flashcards_topic ON student_flashcards(course_id, topic);
