CREATE TABLE IF NOT EXISTS card_review_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flashcard_id INTEGER NOT NULL REFERENCES student_flashcards(id),
    success BOOLEAN NOT NULL,
    reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_card_reviews_flashcard ON card_review_attempts(flashcard_id);
