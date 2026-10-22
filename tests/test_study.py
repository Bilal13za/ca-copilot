"""Tests for Study Coach: retrieval, graceful AI fallback, grading, weak topics."""

from ca_copilot import db, documents, study


def _seed_doc(sample_data, conn):
    res = documents.import_file(sample_data / "study_ias2_summary.md", conn=conn)
    assert res.status == "indexed"
    return res.document_id


def test_retrieve_returns_cited_sources(sample_data):
    conn = db.get_db()
    try:
        doc_id = _seed_doc(sample_data, conn)
        sources = study.retrieve("net realisable value", document_ids=[doc_id],
                                 top_k=3, conn=conn)
        assert sources
        assert all(s.document.endswith("study_ias2_summary.md") for s in sources)
        assert any("realisable" in s.excerpt.lower() for s in sources)
    finally:
        conn.close()


def test_ask_without_ai_falls_back_gracefully(sample_data):
    """No Ollama here -> ask() must return sources, not raise."""
    conn = db.get_db()
    try:
        doc_id = _seed_doc(sample_data, conn)
        settings = {"ai": {"provider": "ollama", "host": "http://127.0.0.1:9",
                           "model": "qwen3:1.7b", "timeout_seconds": 2},
                    "retrieval": {"top_k": 3},
                    "reconciliation": {}, "ocr": {}, "app": {}}
        ans = study.ask("How is inventory measured under IAS 2?",
                        document_ids=[doc_id], settings=settings, conn=conn)
        assert ans.grounded is True
        assert ans.ai_used is False
        assert ans.sources, "fallback must still show retrieved passages"
        assert "realisable" in ans.answer.lower()
    finally:
        conn.close()


def test_ask_with_no_sources_says_so():
    conn = db.get_db()
    try:
        ans = study.ask("Completely unrelated gibberish zzzqqq", conn=conn)
        assert ans.grounded is False
        assert "couldn't find" in ans.answer.lower()
    finally:
        conn.close()


def test_generate_mcqs_without_ai_returns_error(sample_data):
    conn = db.get_db()
    try:
        doc_id = _seed_doc(sample_data, conn)
        settings = {"ai": {"provider": "ollama", "host": "http://127.0.0.1:9",
                           "model": "qwen3:1.7b", "timeout_seconds": 2}}
        out = study.generate_mcqs("IAS 2", document_ids=[doc_id], settings=settings,
                                  conn=conn)
        assert out["ok"] is False
        assert "error" in out
    finally:
        conn.close()


def test_grade_mcq_is_deterministic():
    assert study.grade_mcq("b", "B") is True
    assert study.grade_mcq(" A ", "a") is True
    assert study.grade_mcq("C", "B") is False


def test_weak_topics_detection():
    conn = db.get_db()
    try:
        from ca_copilot import revision
        sid = revision.get_or_create_subject("CAF-1 Test", conn=conn)
        tid_weak = revision.get_or_create_topic(sid, "Weak Topic", conn=conn)
        tid_ok = revision.get_or_create_topic(sid, "Strong Topic", conn=conn)
        for _ in range(4):
            study.record_attempt(subject_id=sid, topic_id=tid_weak, is_correct=False,
                                 question_text="q", conn=conn)
        for _ in range(4):
            study.record_attempt(subject_id=sid, topic_id=tid_ok, is_correct=True,
                                 question_text="q", conn=conn)
        weak = study.weak_topics(conn=conn)
        names = [w["topic"] for w in weak]
        assert "Weak Topic" in names
        assert "Strong Topic" not in names
    finally:
        conn.close()


def test_record_and_history():
    conn = db.get_db()
    try:
        study.record_attempt(question_type="mcq", question_text="2+2?",
                             correct_answer="4", user_answer="4", is_correct=True,
                             conn=conn)
        hist = study.attempt_history(limit=5, conn=conn)
        assert hist and hist[0]["question_text"] == "2+2?"
    finally:
        conn.close()
