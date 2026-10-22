"""Study Coach: document-grounded Q&A, practice questions, and progress tracking.

Principles:
- Answers are grounded in the user's SELECTED documents via keyword retrieval.
- Every grounded answer carries its sources (document, page/section, excerpt).
- If evidence is insufficient, the answer says so instead of guessing.
- Generated questions are labelled as generated — never as official ICAP material.
- Calculations shown step-by-step are drafts; the deterministic workbench owns
  authoritative arithmetic.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

from . import ai, db, documents


@dataclass
class Source:
    document: str
    page: int | None
    section: str | None
    excerpt: str
    chunk_id: int


@dataclass
class StudyAnswer:
    answer: str
    sources: list[Source] = field(default_factory=list)
    grounded: bool = True          # False when answered without usable sources
    ai_used: bool = True
    notice: str = ""               # e.g. "AI unavailable — showing search results"


def retrieve(question: str, *, document_ids: list[int] | None = None,
             top_k: int = 5, max_chars: int = 12000,
             conn=None) -> list[Source]:
    """Keyword retrieval over the selected documents. Returns cited sources."""
    hits = documents.search(question, document_ids=document_ids, limit=top_k * 2, conn=conn)
    sources: list[Source] = []
    total = 0
    for h in hits:
        chunk = documents.get_chunk_text(h["chunk_id"], conn=conn)
        if not chunk:
            continue
        text = chunk["text"]
        if total + len(text) > max_chars:
            text = text[: max(0, max_chars - total)]
        if not text.strip():
            continue
        total += len(text)
        sources.append(Source(document=chunk["filename"], page=chunk["page_number"],
                              section=chunk["section"], excerpt=text,
                              chunk_id=chunk["id"]))
        if total >= max_chars:
            break
    return sources[:top_k]


def _sources_block(sources: list[Source]) -> str:
    lines = []
    for i, s in enumerate(sources, 1):
        loc = s.document
        if s.page:
            loc += f", page {s.page}"
        if s.section:
            loc += f" ({s.section})"
        lines.append(f"[Source {i}: {loc}]\n{s.excerpt}")
    return "\n\n".join(lines)


def citation_label(s: Source) -> str:
    loc = s.document
    if s.page:
        loc += f", p.{s.page}"
    if s.section:
        loc += f" [{s.section}]"
    return loc


def ask(question: str, *, document_ids: list[int] | None = None,
        settings: dict | None = None, conn=None) -> StudyAnswer:
    """Answer a study question grounded in the selected documents."""
    from . import config as config_mod
    settings = settings or config_mod.load()
    top_k = settings.get("retrieval", {}).get("top_k", 5)
    max_chars = settings.get("ai", {}).get("max_context_chars", 12000)

    sources = retrieve(question, document_ids=document_ids, top_k=top_k,
                       max_chars=max_chars, conn=conn)
    if not sources:
        return StudyAnswer(
            answer=("I couldn't find anything about this in the selected documents. "
                    "Try selecting more documents, or rephrase the question with "
                    "keywords from your study material."),
            grounded=False, ai_used=False,
            notice="No relevant sources found in the selected documents.")

    context = _sources_block(sources)
    messages = [
        ai.ChatMessage("system", ai.SYSTEM_GUARDRAILS),
        ai.ChatMessage("user",
                       f"SOURCES:\n{context}\n\nQUESTION: {question}\n\n"
                       "Answer using only the sources above. Cite each factual claim "
                       "as [document, page/section]. If the sources are insufficient, say so."),
    ]
    try:
        provider = ai.make_provider(settings)
        reply = provider.chat(messages, stream=False)
        return StudyAnswer(answer=reply, sources=sources, grounded=True, ai_used=True)
    except ai.AIUnavailable as exc:
        # Graceful fallback: show the retrieved passages directly.
        fallback = ("The local AI model is unavailable, so here are the most relevant "
                    f"passages from your documents instead:\n\n{context}")
        return StudyAnswer(answer=fallback, sources=sources, grounded=True,
                           ai_used=False, notice=str(exc))


def explain_simply(question: str, *, document_ids: list[int] | None = None,
                   settings: dict | None = None, conn=None) -> StudyAnswer:
    """Same as ask(), but requests a plain-language explanation with an example."""
    ans = ask(f"Explain in simple words with a small example: {question}",
              document_ids=document_ids, settings=settings, conn=conn)
    return ans


# ---------------------------------------------------------------- Practice questions

GENERATED_DISCLAIMER = ("Practice material generated by CA Copilot for study only — "
                        "not official ICAP questions or marking schemes.")


def generate_mcqs(topic: str, *, n: int = 5,
                  document_ids: list[int] | None = None,
                  settings: dict | None = None, conn=None) -> dict[str, Any]:
    """Generate MCQs grounded in the selected documents. Requires the AI model."""
    from . import config as config_mod
    settings = settings or config_mod.load()
    sources = retrieve(topic, document_ids=document_ids, top_k=5, conn=conn)
    if not sources:
        return {"ok": False,
                "error": "No source material found for this topic in the selected documents."}
    context = _sources_block(sources)
    messages = [
        ai.ChatMessage("system", ai.SYSTEM_GUARDRAILS + "\n" + GENERATED_DISCLAIMER),
        ai.ChatMessage(
            "user",
            f"SOURCES:\n{context}\n\nWrite {n} multiple-choice questions on '{topic}' "
            "based ONLY on the sources. Reply as a JSON array; each item: "
            '{"question": str, "options": [A,B,C,D], "answer": "A"|"B"|"C"|"D", '
            '"explanation": str with source citation}. No other text.'),
    ]
    try:
        provider = ai.make_provider(settings)
        reply = provider.chat(messages, stream=False)
        start, end = reply.find("["), reply.rfind("]")
        items = json.loads(reply[start:end + 1]) if start != -1 and end != -1 else []
        if not isinstance(items, list) or not items:
            raise ValueError("unparseable")
        cleaned = []
        for it in items[:n]:
            if not all(k in it for k in ("question", "options", "answer")):
                continue
            if len(it["options"]) != 4 or it["answer"] not in "ABCD":
                continue
            cleaned.append(it)
        if not cleaned:
            raise ValueError("unparseable")
        return {"ok": True, "questions": cleaned, "disclaimer": GENERATED_DISCLAIMER,
                "sources": [citation_label(s) for s in sources]}
    except ai.AIUnavailable as exc:
        return {"ok": False, "error": f"MCQ generation needs the local AI model: {exc}"}
    except Exception:
        return {"ok": False, "error": "The model returned questions in an unreadable format. Try again."}


def grade_mcq(user_choice: str, correct: str) -> bool:
    """Deterministic MCQ grading — no AI involved."""
    return user_choice.strip().upper() == correct.strip().upper()


def feedback_on_answer(question: str, user_answer: str, *,
                       reference: str = "", settings: dict | None = None) -> str:
    """Feedback on a theory/numerical answer. Falls back to a checklist without AI."""
    from . import config as config_mod
    settings = settings or config_mod.load()
    ref_block = f"\nREFERENCE (model answer/working):\n{reference}" if reference else ""
    messages = [
        ai.ChatMessage("system", ai.SYSTEM_GUARDRAILS),
        ai.ChatMessage("user",
                       f"QUESTION: {question}\nSTUDENT ANSWER: {user_answer}{ref_block}\n\n"
                       "Give short, kind feedback: what is correct, what is missing or "
                       "wrong, and one concrete improvement. Do not invent a marking scheme."),
    ]
    try:
        return ai.make_provider(settings).chat(messages, stream=False)
    except ai.AIUnavailable:
        return ("AI feedback is unavailable right now. Self-check checklist:\n"
                "1. Did you answer exactly what was asked?\n"
                "2. Did you show each working step with figures?\n"
                "3. Did you state the relevant rule/standard before applying it?\n"
                "4. Did you conclude clearly?")


# ---------------------------------------------------------------- Progress tracking

def record_attempt(*, subject_id: int | None = None, topic_id: int | None = None,
                   document_id: int | None = None, question_type: str = "mcq",
                   question_text: str = "", options: list | None = None,
                   correct_answer: str = "", user_answer: str = "",
                   is_correct: bool | None = None, feedback: str = "",
                   conn=None) -> int:
    own = conn is None
    conn = conn or db.get_db()
    try:
        with db.transaction(conn) as cur:
            cur.execute(
                """INSERT INTO practice_attempts
                   (subject_id, topic_id, document_id, question_type, question_text,
                    options_json, correct_answer, user_answer, is_correct, feedback)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (subject_id, topic_id, document_id, question_type, question_text,
                 json.dumps(options) if options else None, correct_answer, user_answer,
                 None if is_correct is None else int(is_correct), feedback or None),
            )
            return cur.lastrowid
    finally:
        if own:
            conn.close()


def weak_topics(*, min_attempts: int = 3, accuracy_below: float = 0.6,
                conn=None) -> list[dict[str, Any]]:
    """Topics with enough attempts but low accuracy — the revision hit-list."""
    own = conn is None
    conn = conn or db.get_db()
    try:
        rows = conn.execute(
            """SELECT t.id, t.name AS topic, s.name AS subject,
                      COUNT(*) AS attempts,
                      SUM(CASE WHEN pa.is_correct = 1 THEN 1 ELSE 0 END) AS correct
               FROM practice_attempts pa
               JOIN topics t ON t.id = pa.topic_id
               JOIN subjects s ON s.id = t.subject_id
               WHERE pa.is_correct IS NOT NULL
               GROUP BY t.id HAVING COUNT(*) >= ?
               ORDER BY (1.0 * SUM(CASE WHEN pa.is_correct = 1 THEN 1 ELSE 0 END) / COUNT(*))""",
            (min_attempts,)).fetchall()
        out = []
        for r in rows:
            acc = (r["correct"] or 0) / r["attempts"]
            if acc < accuracy_below:
                d = dict(r)
                d["accuracy"] = round(acc, 2)
                out.append(d)
        return out
    finally:
        if own:
            conn.close()


def attempt_history(*, limit: int = 50, conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or db.get_db()
    try:
        rows = conn.execute(
            """SELECT pa.*, t.name AS topic, s.name AS subject
               FROM practice_attempts pa
               LEFT JOIN topics t ON t.id = pa.topic_id
               LEFT JOIN subjects s ON s.id = pa.subject_id
               ORDER BY pa.attempted_at DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()
