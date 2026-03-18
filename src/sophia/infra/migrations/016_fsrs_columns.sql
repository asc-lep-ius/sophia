ALTER TABLE review_schedule ADD COLUMN difficulty REAL DEFAULT 0.3;
ALTER TABLE review_schedule ADD COLUMN stability REAL DEFAULT 1.0;
ALTER TABLE review_schedule ADD COLUMN review_count INTEGER DEFAULT 0;
