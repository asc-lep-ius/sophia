CREATE TABLE IF NOT EXISTS self_explanations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flashcard_id INTEGER NOT NULL REFERENCES student_flashcards(id),
    student_explanation TEXT NOT NULL,
    scaffold_level INTEGER NOT NULL DEFAULT 3 CHECK(scaffold_level BETWEEN 0 AND 3),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_self_explanations_flashcard ON self_explanations(flashcard_id);
