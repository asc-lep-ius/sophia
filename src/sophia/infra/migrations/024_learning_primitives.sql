CREATE TABLE IF NOT EXISTS learning_path_settings (
    course_id INTEGER PRIMARY KEY,
    exam_language TEXT NOT NULL DEFAULT 'de',
    content_origin TEXT NOT NULL DEFAULT 'tuwel',
    org_id TEXT NOT NULL DEFAULT 'default',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS content_provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_kind TEXT NOT NULL,
    content_id TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    content_origin TEXT NOT NULL DEFAULT 'tuwel',
    generated_by TEXT NOT NULL,
    generator_ref TEXT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verified_by TEXT,
    verified_at TIMESTAMP,
    org_id TEXT NOT NULL DEFAULT 'default',
    UNIQUE(content_kind, content_id)
);

CREATE INDEX IF NOT EXISTS idx_content_provenance_scope
    ON content_provenance(course_id, content_kind);

CREATE TABLE IF NOT EXISTS content_source_spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provenance_id INTEGER NOT NULL REFERENCES content_provenance(id) ON DELETE CASCADE,
    content_item_id TEXT NOT NULL,
    start_char INTEGER,
    end_char INTEGER,
    start_ms INTEGER,
    end_ms INTEGER,
    excerpt TEXT
);

CREATE INDEX IF NOT EXISTS idx_content_source_spans_provenance
    ON content_source_spans(provenance_id);

CREATE TABLE IF NOT EXISTS content_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_kind TEXT NOT NULL,
    content_id TEXT NOT NULL,
    language TEXT NOT NULL,
    translated_text TEXT NOT NULL DEFAULT '',
    course_id INTEGER NOT NULL,
    org_id TEXT NOT NULL DEFAULT 'default',
    translated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(content_kind, content_id, language)
);

CREATE TABLE IF NOT EXISTS generated_questions (
    id TEXT PRIMARY KEY,
    course_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    kind TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL,
    content_language TEXT NOT NULL DEFAULT 'de',
    options TEXT NOT NULL DEFAULT '[]',
    segments TEXT NOT NULL DEFAULT '[]',
    elaboration_policy TEXT,
    org_id TEXT NOT NULL DEFAULT 'default',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_generated_questions_scope
    ON generated_questions(course_id, topic);

CREATE TABLE IF NOT EXISTS learning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    course_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMP NOT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id INTEGER,
    question_id TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    org_id TEXT NOT NULL DEFAULT 'default'
);

CREATE INDEX IF NOT EXISTS idx_learning_events_trace
    ON learning_events(course_id, question_id, user_id, event_type);

CREATE INDEX IF NOT EXISTS idx_learning_events_retention
    ON learning_events(received_at);

CREATE TABLE IF NOT EXISTS question_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    question_id TEXT NOT NULL REFERENCES generated_questions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    confidence INTEGER,
    org_id TEXT NOT NULL DEFAULT 'default',
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_question_attempts_scope
    ON question_attempts(course_id, question_id, user_id);
