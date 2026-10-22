"""Tests for the database layer and migrations."""

from ca_copilot import db, paths


def test_migrate_creates_all_tables():
    conn = db.get_db()
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','virtual table')")}
        for expected in ("documents", "doc_chunks", "doc_chunks_fts", "chats",
                         "chat_messages", "subjects", "topics", "notes",
                         "practice_attempts", "revision_tasks", "analysis_jobs",
                         "report_files", "settings_kv", "tax_rule_sources",
                         "schema_migrations"):
            assert expected in tables, f"missing table {expected}"
    finally:
        conn.close()


def test_migrate_is_idempotent():
    conn = db.get_db()  # get_db() already applies pending migrations
    try:
        assert db.migrate(conn) == []
        assert db.migrate(conn) == []
        applied = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        assert applied == {"001_initial"}
    finally:
        conn.close()


def test_parameterized_insert_and_foreign_keys():
    conn = db.get_db()
    try:
        with db.transaction(conn) as cur:
            cur.execute("INSERT INTO subjects(name) VALUES (?)", ("CAF-1",))
            sid = cur.lastrowid
            cur.execute("INSERT INTO topics(subject_id, name) VALUES (?, ?)",
                        (sid, "IAS 2"))
        # malicious-looking input must be stored literally, not executed
        evil = "x'); DROP TABLE subjects; --"
        with db.transaction(conn) as cur:
            cur.execute("INSERT INTO subjects(name) VALUES (?)", (evil,))
        assert conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 2
    finally:
        conn.close()


def test_db_file_lives_in_data_dir():
    conn = db.get_db()
    try:
        assert str(paths.db_path()).endswith("app.db")
        assert paths.db_path().exists()
    finally:
        conn.close()
