CREATE TABLE IF NOT EXISTS lecture_modules (
    module_id INTEGER PRIMARY KEY,
    course_name TEXT NOT NULL DEFAULT '',
    course_shortname TEXT NOT NULL DEFAULT ''
);
