CREATE TABLE IF NOT EXISTS downloads (
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
);

CREATE TABLE IF NOT EXISTS book_cache (
    isbn TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    metadata_json TEXT,
    last_searched TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metacognition_log (
    domain TEXT NOT NULL,
    item_id TEXT NOT NULL,
    predicted REAL NOT NULL,
    actual REAL,
    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actual_at TIMESTAMP,
    PRIMARY KEY (domain, item_id)
);
