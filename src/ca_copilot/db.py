"""SQLite access with explicit, versioned migrations.

- One database file: <data_dir>/app.db
- All SQL is parameterized; every write runs inside a transaction.
- Schema changes are applied by numbered migration files in migrations/.
- Upgrades never delete user data.

Tables (v1):
    schema_migrations  which migrations have been applied
    documents          imported files + extracted text metadata
    doc_chunks         text chunks for retrieval (FTS5 index)
    chats / chat_messages
    notes              saved notes + bookmarks
    subjects / topics  study organisation
    doc_subjects       links documents to subjects/topics
    practice_attempts  question attempts and results
    revision_tasks     revision tasks with due dates
    analysis_jobs      workbench runs: source files, settings, time, summary
    report_files       exported report files per job
    settings_kv        small key/value store (UI state, counters)
    tax_rule_sources   versioned tax rule sources (framework; see tax_rules.py)
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Serializes concurrent use of a single connection from multiple threads.
# The app opens one connection per Streamlit script run, but Streamlit may
# execute reruns on different threads and a connection can end up shared
# across them; without the lock, overlapping transactions on one connection
# fail with "cannot start a transaction within a transaction". Reentrant so
# nested transaction() calls on the same thread stay safe.
_lock = threading.RLock()

from . import paths

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def connect(db_file: Path | None = None) -> sqlite3.Connection:
    db_file = db_file or paths.db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    # Thread affinity check disabled. Every caller in this codebase opens its
    # own connection and uses it on one thread only (the Streamlit UI opens a
    # fresh connection per script run — see app.py). The flag is a safety net
    # so a future slip surfaces as an ordinary SQLite error rather than
    # sqlite3.ProgrammingError.
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    with _lock:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _applied(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    return {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}


def migrate(conn: sqlite3.Connection | None = None) -> list[str]:
    """Apply any pending migrations in filename order. Returns applied names."""
    own = conn is None
    conn = conn or connect()
    try:
        applied = _applied(conn)
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        newly: list[str] = []
        for path in files:
            name = path.stem  # e.g. 001_initial
            if name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            with transaction(conn) as cur:
                cur.executescript(sql)
                # OR IGNORE: two threads racing migrate() on a fresh database
                # must not fail on the unique migration name.
                cur.execute(
                    "INSERT OR IGNORE INTO schema_migrations(name) VALUES (?)", (name,)
                )
            newly.append(name)
        return newly
    finally:
        if own:
            conn.close()


def get_db() -> sqlite3.Connection:
    """Open the app database and ensure migrations are applied."""
    conn = connect()
    migrate(conn)
    return conn
