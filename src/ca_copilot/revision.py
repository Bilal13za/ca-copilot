"""Revision Tracker: tasks with due dates, notes, bookmarks, subjects/topics."""

from __future__ import annotations

from typing import Any

from . import db


# ---------------------------------------------------------------- Subjects & topics

def get_or_create_subject(name: str, *, exam_session: str = "", conn=None) -> int:
    own = conn is None
    conn = conn or db.get_db()
    try:
        row = conn.execute("SELECT id FROM subjects WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        with db.transaction(conn) as cur:
            cur.execute("INSERT INTO subjects(name, exam_session) VALUES (?, ?)",
                        (name, exam_session or None))
            return cur.lastrowid
    finally:
        if own:
            conn.close()


def get_or_create_topic(subject_id: int, name: str, conn=None) -> int:
    own = conn is None
    conn = conn or db.get_db()
    try:
        row = conn.execute(
            "SELECT id FROM topics WHERE subject_id = ? AND name = ?",
            (subject_id, name)).fetchone()
        if row:
            return row["id"]
        with db.transaction(conn) as cur:
            cur.execute("INSERT INTO topics(subject_id, name) VALUES (?, ?)",
                        (subject_id, name))
            return cur.lastrowid
    finally:
        if own:
            conn.close()


def list_subjects(conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM subjects ORDER BY name")]
    finally:
        if own:
            conn.close()


def list_topics(subject_id: int, conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM topics WHERE subject_id = ? ORDER BY name", (subject_id,))]
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------- Revision tasks

def add_task(title: str, *, subject_id: int | None = None,
             topic_id: int | None = None, due_date: str = "",
             priority: str = "medium", conn=None) -> int:
    own = conn is None
    conn = conn or db.get_db()
    try:
        with db.transaction(conn) as cur:
            cur.execute(
                """INSERT INTO revision_tasks(title, subject_id, topic_id, due_date, priority)
                   VALUES (?, ?, ?, ?, ?)""",
                (title, subject_id, topic_id, due_date or None, priority))
            return cur.lastrowid
    finally:
        if own:
            conn.close()


def list_tasks(*, status: str | None = None, conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or db.get_db()
    try:
        sql = """SELECT rt.*, s.name AS subject, t.name AS topic
                 FROM revision_tasks rt
                 LEFT JOIN subjects s ON s.id = rt.subject_id
                 LEFT JOIN topics t ON t.id = rt.topic_id"""
        params: list[Any] = []
        if status:
            sql += " WHERE rt.status = ?"
            params.append(status)
        sql += " ORDER BY CASE WHEN rt.due_date IS NULL THEN 1 ELSE 0 END, rt.due_date"
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        if own:
            conn.close()


def complete_task(task_id: int, conn=None) -> None:
    own = conn is None
    conn = conn or db.get_db()
    try:
        with db.transaction(conn) as cur:
            cur.execute(
                "UPDATE revision_tasks SET status = 'done', completed_at = datetime('now')"
                " WHERE id = ?", (task_id,))
    finally:
        if own:
            conn.close()


def delete_task(task_id: int, conn=None) -> None:
    own = conn is None
    conn = conn or db.get_db()
    try:
        with db.transaction(conn) as cur:
            cur.execute("DELETE FROM revision_tasks WHERE id = ?", (task_id,))
    finally:
        if own:
            conn.close()


def overdue_tasks(today: str, conn=None) -> list[dict[str, Any]]:
    """Tasks with due_date before `today` (YYYY-MM-DD) still pending."""
    own = conn is None
    conn = conn or db.get_db()
    try:
        rows = conn.execute(
            """SELECT rt.*, s.name AS subject FROM revision_tasks rt
               LEFT JOIN subjects s ON s.id = rt.subject_id
               WHERE rt.status = 'pending' AND rt.due_date IS NOT NULL
                 AND rt.due_date < ? ORDER BY rt.due_date""", (today,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------- Notes & bookmarks

def save_note(title: str, body: str, *, document_id: int | None = None,
              page_number: int | None = None, subject_id: int | None = None,
              topic_id: int | None = None, is_bookmark: bool = False,
              conn=None) -> int:
    own = conn is None
    conn = conn or db.get_db()
    try:
        with db.transaction(conn) as cur:
            cur.execute(
                """INSERT INTO notes(title, body, document_id, page_number,
                                     subject_id, topic_id, is_bookmark)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (title, body, document_id, page_number, subject_id, topic_id,
                 int(is_bookmark)))
            return cur.lastrowid
    finally:
        if own:
            conn.close()


def list_notes(*, bookmarks_only: bool = False, limit: int = 100,
               conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or db.get_db()
    try:
        sql = """SELECT n.*, d.filename AS document_name, s.name AS subject
                 FROM notes n
                 LEFT JOIN documents d ON d.id = n.document_id
                 LEFT JOIN subjects s ON s.id = n.subject_id"""
        if bookmarks_only:
            sql += " WHERE n.is_bookmark = 1"
        sql += " ORDER BY n.updated_at DESC LIMIT ?"
        return [dict(r) for r in conn.execute(sql, (limit,))]
    finally:
        if own:
            conn.close()


def delete_note(note_id: int, conn=None) -> None:
    own = conn is None
    conn = conn or db.get_db()
    try:
        with db.transaction(conn) as cur:
            cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    finally:
        if own:
            conn.close()
