-- 001_initial.sql — base schema for CA Copilot Local.
-- All timestamps are UTC ISO-8601 text. Foreign keys enforced by the app.

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    filename      TEXT NOT NULL,
    stored_path   TEXT NOT NULL,            -- path of the imported copy, relative to documents/
    file_type     TEXT NOT NULL,            -- pdf, docx, txt, md, csv, xlsx
    file_size     INTEGER NOT NULL DEFAULT 0,
    sha256        TEXT,                     -- duplicate detection
    page_count    INTEGER,
    status        TEXT NOT NULL DEFAULT 'indexed',  -- indexed | needs_ocr | failed | unsupported
    ocr_used      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,                     -- why failed/unsupported, if any
    imported_at   TEXT NOT NULL DEFAULT (datetime('now')),
    source_note   TEXT                      -- provenance note, e.g. "ICAP CAF-1 study pack"
);

CREATE TABLE IF NOT EXISTS doc_chunks (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    page_number  INTEGER,                   -- NULL when not applicable
    section      TEXT,                      -- sheet name / heading context, when known
    text         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc ON doc_chunks(document_id);

-- Full-text search over chunks. The FTS table keeps its own copy of the text
-- (internal content) so snippets and stored IDs read back reliably.
CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts USING fts5(
    text, document_id UNINDEXED, chunk_id UNINDEXED, tokenize='porter'
);
CREATE TRIGGER IF NOT EXISTS trg_chunks_ai AFTER INSERT ON doc_chunks BEGIN
    INSERT INTO doc_chunks_fts(rowid, text, document_id, chunk_id)
    VALUES (new.id, new.text, new.document_id, new.id);
END;
CREATE TRIGGER IF NOT EXISTS trg_chunks_ad AFTER DELETE ON doc_chunks BEGIN
    DELETE FROM doc_chunks_fts WHERE rowid = old.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_chunks_au AFTER UPDATE ON doc_chunks BEGIN
    DELETE FROM doc_chunks_fts WHERE rowid = old.id;
    INSERT INTO doc_chunks_fts(rowid, text, document_id, chunk_id)
    VALUES (new.id, new.text, new.document_id, new.id);
END;

CREATE TABLE IF NOT EXISTS chats (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT 'Chat',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,              -- user | assistant | system
    content     TEXT NOT NULL,
    sources_json TEXT,                      -- JSON list of {document, page, section, excerpt}
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id);

CREATE TABLE IF NOT EXISTS subjects (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,      -- e.g. "CAF-1 Financial Accounting and Reporting I"
    exam_session TEXT,                      -- e.g. "Spring 2027"
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(subject_id, name)
);

CREATE TABLE IF NOT EXISTS doc_subjects (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    subject_id  INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    topic_id    INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    PRIMARY KEY (document_id, subject_id, topic_id)
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    page_number INTEGER,
    subject_id  INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    topic_id    INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    is_bookmark INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notes_doc ON notes(document_id);

CREATE TABLE IF NOT EXISTS practice_attempts (
    id            INTEGER PRIMARY KEY,
    subject_id    INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    topic_id      INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    document_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    question_type TEXT NOT NULL DEFAULT 'mcq',   -- mcq | theory | numerical
    question_text TEXT NOT NULL,
    options_json  TEXT,                           -- JSON list for MCQs
    correct_answer TEXT,
    user_answer   TEXT,
    is_correct    INTEGER,                        -- 1/0/NULL (ungraded)
    feedback      TEXT,
    attempted_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS revision_tasks (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    subject_id   INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    topic_id     INTEGER REFERENCES topics(id) ON DELETE SET NULL,
    due_date     TEXT,                             -- YYYY-MM-DD
    priority     TEXT NOT NULL DEFAULT 'medium',   -- low | medium | high
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | done
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_revision_due ON revision_tasks(due_date, status);

CREATE TABLE IF NOT EXISTS analysis_jobs (
    id               INTEGER PRIMARY KEY,
    kind             TEXT NOT NULL,          -- inspection | duplicates | reconciliation | validation
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    source_files_json TEXT NOT NULL,         -- JSON list of {label, filename, sha256}
    settings_json    TEXT NOT NULL,          -- JSON of the exact settings used
    summary_json     TEXT NOT NULL           -- JSON summary of findings
);

CREATE TABLE IF NOT EXISTS report_files (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    path       TEXT NOT NULL,                -- relative to reports/
    format     TEXT NOT NULL,                -- csv | xlsx
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Framework for FUTURE Pakistan tax support: every rule must cite a versioned source.
-- The first release ships NO tax rates and performs NO tax calculations.
CREATE TABLE IF NOT EXISTS tax_rule_sources (
    id             INTEGER PRIMARY KEY,
    tax_year       TEXT NOT NULL,            -- e.g. "2026"
    title          TEXT NOT NULL,
    source_ref     TEXT NOT NULL,            -- e.g. "Income Tax Ordinance, 2001 s.12(1) — FBR website, accessed 2026-10-21"
    effective_date TEXT,
    added_at       TEXT NOT NULL DEFAULT (datetime('now')),
    notes          TEXT
);
