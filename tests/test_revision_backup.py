"""Tests for revision tracker, backup/restore, AI provider guards, tax framework."""

import zipfile

import pytest

from ca_copilot import ai, backup, db, revision, tax_rules


# ---------------------------------------------------------------- revision

def test_task_lifecycle():
    conn = db.get_db()
    try:
        tid = revision.add_task("Revise IAS 2", due_date="2026-11-01", priority="high",
                                conn=conn)
        tasks = revision.list_tasks(conn=conn)
        assert len(tasks) == 1 and tasks[0]["title"] == "Revise IAS 2"
        revision.complete_task(tid, conn=conn)
        assert revision.list_tasks(status="done", conn=conn)[0]["status"] == "done"
        assert revision.list_tasks(status="pending", conn=conn) == []
    finally:
        conn.close()


def test_overdue_tasks():
    conn = db.get_db()
    try:
        revision.add_task("Old task", due_date="2020-01-01", conn=conn)
        revision.add_task("Future task", due_date="2099-01-01", conn=conn)
        overdue = revision.overdue_tasks("2026-10-21", conn=conn)
        assert [t["title"] for t in overdue] == ["Old task"]
    finally:
        conn.close()


def test_notes_and_bookmarks():
    conn = db.get_db()
    try:
        nid = revision.save_note("NRV rule", "Lower of cost and NRV (IAS 2.9).",
                                 is_bookmark=True, conn=conn)
        revision.save_note("plain note", "body", conn=conn)
        assert len(revision.list_notes(conn=conn)) == 2
        bm = revision.list_notes(bookmarks_only=True, conn=conn)
        assert len(bm) == 1 and bm[0]["id"] == nid
        revision.delete_note(nid, conn=conn)
        assert len(revision.list_notes(conn=conn)) == 1
    finally:
        conn.close()


def test_subjects_topics_idempotent():
    conn = db.get_db()
    try:
        s1 = revision.get_or_create_subject("CAF-2")
        s2 = revision.get_or_create_subject("CAF-2")
        assert s1 == s2
        t1 = revision.get_or_create_topic(s1, "Tax basics")
        assert revision.get_or_create_topic(s1, "Tax basics") == t1
    finally:
        conn.close()


# ---------------------------------------------------------------- backup

def test_backup_and_restore_roundtrip(tmp_path):
    from ca_copilot import config
    config.load()  # ensure config.json exists alongside app.db
    conn = db.get_db()
    try:
        revision.add_task("Keep me", conn=conn)
    finally:
        conn.close()
    zf = backup.create_backup()
    assert zf.exists() and zipfile.is_zipfile(zf)
    info = backup.inspect_backup(zf)
    assert info["has_database"] and info["has_config"]

    target = tmp_path / "restored"
    out = backup.restore_backup(zf, target)
    assert (out / "app.db").exists()

    # non-empty target must be refused
    with pytest.raises(ValueError):
        backup.restore_backup(zf, tmp_path / "restored")


def test_list_backups_sorted():
    b1 = backup.create_backup()
    b2 = backup.create_backup()
    listed = backup.list_backups()
    assert listed[0] == b2 and listed[1] == b1


# ---------------------------------------------------------------- ai provider

def test_ollama_refuses_non_localhost():
    with pytest.raises(ValueError):
        ai.OllamaProvider("https://api.example.com", "qwen3:1.7b")


def test_ai_status_reports_unreachable_gracefully():
    settings = {"ai": {"provider": "ollama", "host": "http://127.0.0.1:9",
                       "model": "qwen3:1.7b", "timeout_seconds": 1}}
    st = ai.get_status(settings)
    assert st.reachable is False
    assert "not running" in st.message


def test_unknown_provider_is_unavailable():
    st = ai.get_status({"ai": {"provider": "nope"}})
    assert st.reachable is False


# ---------------------------------------------------------------- tax framework

def test_tax_computation_refuses():
    with pytest.raises(NotImplementedError):
        tax_rules.compute_tax_liability(tax_year="2026", income=100000)


def test_rule_source_roundtrip():
    conn = db.get_db()
    try:
        rid = tax_rules.add_rule_source(tax_rules.TaxRuleSource(
            tax_year="2026", title="Test rule",
            source_ref="Income Tax Ordinance, 2001 s.12 — test only"), conn=conn)
        sources = tax_rules.list_rule_sources("2026", conn=conn)
        assert any(s["id"] == rid for s in sources)
    finally:
        conn.close()
