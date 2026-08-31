-- Snapshot of the SQLite schema as it stood at migration 024, kept so the
-- one-shot sqlite_to_postgres migration stays testable after the numbered
-- migrations were removed. Frozen on purpose: it describes databases that
-- already exist in the field, not a schema anything still evolves.
CREATE TABLE active_timers (
    deadline_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE book_cache (
    isbn TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    metadata_json TEXT,
    last_searched TIMESTAMP
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE card_review_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flashcard_id INTEGER NOT NULL REFERENCES student_flashcards(id),
    success BOOLEAN NOT NULL,
    reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE confidence_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    predicted REAL NOT NULL CHECK(predicted BETWEEN 0.0 AND 1.0),
    actual REAL CHECK(actual IS NULL OR actual BETWEEN 0.0 AND 1.0),
    rated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actual_at TIMESTAMP
, org_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE content_provenance (
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
CREATE TABLE content_source_spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provenance_id INTEGER NOT NULL REFERENCES content_provenance(id) ON DELETE CASCADE,
    content_item_id TEXT NOT NULL,
    start_char INTEGER,
    end_char INTEGER,
    start_ms INTEGER,
    end_ms INTEGER,
    excerpt TEXT
);
CREATE TABLE content_translations (
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
CREATE TABLE course_materials (
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
, org_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE deadline_cache (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    course_name TEXT NOT NULL DEFAULT '',
    deadline_type TEXT NOT NULL,
    due_at TEXT NOT NULL,
    grade_weight REAL,
    submission_status TEXT,
    url TEXT,
    extra TEXT DEFAULT '{}',
    synced_at TEXT NOT NULL DEFAULT (datetime('now'))
, org_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE deadline_reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deadline_id TEXT NOT NULL,
    predicted_hours REAL,
    actual_hours REAL,
    reflection_text TEXT,
    reflected_at TEXT NOT NULL DEFAULT (datetime('now'))
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE discovered_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    isbn TEXT,
    source TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    course_name TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, org_id TEXT NOT NULL DEFAULT 'default',
    UNIQUE(title, course_id, source)
);
CREATE TABLE downloads (
    md5 TEXT PRIMARY KEY,
    isbn TEXT,
    title TEXT NOT NULL,
    authors TEXT,
    format TEXT NOT NULL,
    size_bytes INTEGER,
    path TEXT NOT NULL,
    source TEXT NOT NULL,
    is_open_access BOOLEAN DEFAULT FALSE,
    retail_price REAL,
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE effort_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deadline_id TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    predicted_hours REAL NOT NULL CHECK(predicted_hours > 0),
    breakdown TEXT,
    implementation_intention TEXT,
    scaffold_level TEXT NOT NULL DEFAULT 'full',
    estimated_at TEXT NOT NULL DEFAULT (datetime('now'))
, org_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE generated_questions (
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
CREATE TABLE knowledge_index (
    episode_id TEXT PRIMARY KEY REFERENCES transcriptions(episode_id),
    module_id INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    indexed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE learning_events (
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
CREATE TABLE learning_path_settings (
    course_id INTEGER PRIMARY KEY,
    exam_language TEXT NOT NULL DEFAULT 'de',
    content_origin TEXT NOT NULL DEFAULT 'tuwel',
    org_id TEXT NOT NULL DEFAULT 'default',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE lecture_downloads (
    episode_id TEXT PRIMARY KEY,
    module_id INTEGER NOT NULL,
    series_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    track_url TEXT NOT NULL,
    track_mimetype TEXT NOT NULL,
    file_path TEXT,
    file_size_bytes INTEGER,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, skip_reason TEXT, lecture_number INTEGER, missed_at TIMESTAMP DEFAULT NULL, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE lecture_modules (
    module_id INTEGER PRIMARY KEY,
    course_name TEXT NOT NULL DEFAULT '',
    course_shortname TEXT NOT NULL DEFAULT ''
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE metacognition_log (
    domain TEXT NOT NULL,
    item_id TEXT NOT NULL,
    predicted REAL NOT NULL,
    actual REAL,
    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actual_at TIMESTAMP, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default',
    PRIMARY KEY (domain, item_id)
);
CREATE TABLE question_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    question_id TEXT NOT NULL REFERENCES generated_questions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    confidence INTEGER,
    org_id TEXT NOT NULL DEFAULT 'default',
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE review_schedule (
    topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    interval_index INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TIMESTAMP,
    next_review_at TIMESTAMP NOT NULL,
    score_at_last_review REAL, difficulty REAL DEFAULT 0.3, stability REAL DEFAULT 1.0, review_count INTEGER DEFAULT 0, org_id TEXT NOT NULL DEFAULT 'default',
    PRIMARY KEY (topic, course_id)
);
CREATE TABLE scheduled_jobs (
    job_id     TEXT PRIMARY KEY,
    command    TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    description TEXT NOT NULL DEFAULT ''
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE self_explanations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flashcard_id INTEGER NOT NULL REFERENCES student_flashcards(id),
    student_explanation TEXT NOT NULL,
    scaffold_level INTEGER NOT NULL DEFAULT 3 CHECK(scaffold_level BETWEEN 0 AND 3),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE student_flashcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'study' CHECK(source IN ('study', 'lecture', 'manual')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, org_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    pre_test_score REAL CHECK(pre_test_score IS NULL OR pre_test_score BETWEEN 0.0 AND 1.0),
    post_test_score REAL CHECK(post_test_score IS NULL OR post_test_score BETWEEN 0.0 AND 1.0),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
, org_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE time_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deadline_id TEXT NOT NULL,
    hours REAL NOT NULL CHECK(hours > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    note TEXT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE topic_lecture_links (
    topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    chunk_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, org_id TEXT NOT NULL DEFAULT 'default',
    PRIMARY KEY (topic, course_id, chunk_id)
);
CREATE TABLE topic_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'lecture' CHECK(source IN ('lecture', 'quiz', 'manual')),
    frequency INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, org_id TEXT NOT NULL DEFAULT 'default',
    UNIQUE(topic, course_id, source)
);
CREATE TABLE topic_reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_topic TEXT NOT NULL,
    moodle_topic TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    similarity REAL NOT NULL,
    reconciled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, org_id TEXT NOT NULL DEFAULT 'default',
    UNIQUE(manual_topic, course_id)
);
CREATE TABLE transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES transcriptions(episode_id),
    segment_index INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    text TEXT NOT NULL
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE TABLE transcriptions (
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
, org_id TEXT NOT NULL DEFAULT 'default', course_id TEXT NOT NULL DEFAULT 'default');
CREATE INDEX idx_lecture_downloads_module ON lecture_downloads(module_id);
CREATE INDEX idx_lecture_downloads_status ON lecture_downloads(status);
CREATE INDEX idx_transcript_segments_episode ON transcript_segments(episode_id);
CREATE INDEX idx_transcriptions_status ON transcriptions(status);
CREATE INDEX idx_knowledge_index_status ON knowledge_index(status);
CREATE INDEX idx_topic_mappings_course ON topic_mappings(course_id);
CREATE INDEX idx_topic_lecture_links_course ON topic_lecture_links(course_id);
CREATE INDEX idx_topic_lecture_links_episode ON topic_lecture_links(episode_id);
CREATE INDEX idx_confidence_ratings_course ON confidence_ratings(course_id);
CREATE INDEX idx_confidence_ratings_topic ON confidence_ratings(course_id, topic);
CREATE INDEX idx_study_sessions_course ON study_sessions(course_id);
CREATE INDEX idx_study_sessions_topic ON study_sessions(course_id, topic);
CREATE INDEX idx_flashcards_course ON student_flashcards(course_id);
CREATE INDEX idx_flashcards_topic ON student_flashcards(course_id, topic);
CREATE INDEX idx_card_reviews_flashcard ON card_review_attempts(flashcard_id);
CREATE INDEX idx_self_explanations_flashcard ON self_explanations(flashcard_id);
CREATE INDEX idx_review_schedule_due ON review_schedule(next_review_at);
CREATE INDEX idx_discovered_refs_course ON discovered_references(course_id);
CREATE INDEX idx_discovered_refs_isbn ON discovered_references(isbn);
CREATE INDEX idx_discovered_refs_course_name ON discovered_references(course_name);
CREATE UNIQUE INDEX uq_course_materials_url
    ON course_materials(course_id, url);
CREATE INDEX idx_deadline_cache_course ON deadline_cache(course_id);
CREATE INDEX idx_deadline_cache_due ON deadline_cache(due_at);
CREATE INDEX idx_effort_estimates_deadline ON effort_estimates(deadline_id);
CREATE INDEX idx_effort_estimates_course ON effort_estimates(course_id);
CREATE INDEX idx_time_entries_deadline ON time_entries(deadline_id);
CREATE INDEX idx_content_provenance_scope
    ON content_provenance(course_id, content_kind);
CREATE INDEX idx_content_source_spans_provenance
    ON content_source_spans(provenance_id);
CREATE INDEX idx_generated_questions_scope
    ON generated_questions(course_id, topic);
CREATE INDEX idx_learning_events_trace
    ON learning_events(course_id, question_id, user_id, event_type);
CREATE INDEX idx_learning_events_retention
    ON learning_events(received_at);
CREATE INDEX idx_question_attempts_scope
    ON question_attempts(course_id, question_id, user_id);
