"""CA Copilot Local — Streamlit desktop UI (localhost only).

Run:  streamlit run app.py
The app binds to 127.0.0.1 only (see run_windows.bat). No data leaves the PC.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ca_copilot import ai, backup, config, db, documents, paths, revision, study, tax_rules
from ca_copilot import workbench as wb
from ca_copilot.workbench import ColumnMap, ValidationRules

st.set_page_config(page_title="CA Copilot", page_icon="📚", layout="wide")


# ---------------------------------------------------------------- bootstrap

@st.cache_resource
def get_settings():
    return config.load()


settings = get_settings()
# One database connection per script run. Streamlit may execute reruns on
# different threads, so a cached/shared connection crashes with
# "SQLite objects created in a thread can only be used in that same thread".
# A fresh per-run connection is cheap and always thread-correct.
conn = db.get_db()
settings["ai"]["stream"] = False  # chat() streaming is opt-in per call

PRIVACY_BADGE = "🔒 100% local — no data leaves this computer"


def ai_status_badge() -> str:
    st_ = ai.get_status(settings)
    if st_.reachable and not st_.message.startswith("Model"):
        return f"🟢 AI: {st_.active_model} ready"
    if st_.reachable:
        return "🟡 AI: model not installed"
    return "⚪ AI: unavailable (search + tools still work)"


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.title("📚 CA Copilot")
    st.caption(PRIVACY_BADGE)
    st.caption(ai_status_badge())
    st.divider()
    section = st.radio(
        "Go to",
        ["Dashboard", "Study Coach", "Document Library",
         "Accounting Workbench", "Revision Tracker", "Settings & Diagnostics"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption(f"Data: {paths.data_dir()}")


# ================================================================ DASHBOARD

def show_dashboard():
    st.header("Dashboard")
    st.caption("Your study workspace at a glance. " + PRIVACY_BADGE)

    docs = documents.list_documents(conn=conn)
    tasks = revision.list_tasks(status="pending", conn=conn)
    overdue = revision.overdue_tasks(date.today().isoformat(), conn=conn)
    notes = revision.list_notes(limit=5, conn=conn)
    weak = study.weak_topics(conn=conn)
    jobs = conn.execute(
        "SELECT * FROM analysis_jobs ORDER BY created_at DESC LIMIT 5").fetchall()
    chats = conn.execute(
        "SELECT * FROM chats ORDER BY updated_at DESC LIMIT 5").fetchall()

    if overdue:
        st.error(f"⚠️ {len(overdue)} overdue revision task(s): "
                 + ", ".join(t["title"] for t in overdue[:5]))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents", len(documents.list_documents(conn=conn)))
    c2.metric("Pending tasks", len(tasks))
    c3.metric("Weak topics", len(weak))
    c4.metric("Analyses run", conn.execute("SELECT COUNT(*) FROM analysis_jobs").fetchone()[0])

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Recent documents")
        if docs:
            for d in docs[:5]:
                icon = {"pdf": "📕", "docx": "📘", "xlsx": "📊", "csv": "📄"}.get(d["file_type"], "📄")
                st.write(f"{icon} **{d['filename']}** — {d['status']} "
                         f"({d['chunks']} indexed passages)")
        else:
            st.info("No documents yet. Import study material in the Document Library.")
        st.subheader("Recent chats")
        if chats:
            for ch in chats:
                st.write(f"💬 {ch['title']} — {ch['updated_at'][:16]}")
        else:
            st.info("No study chats yet.")
    with col_b:
        st.subheader("Upcoming revision tasks")
        if tasks:
            for t in tasks[:5]:
                due = f" (due {t['due_date']})" if t["due_date"] else ""
                st.write(f"{'🔴' if t['priority'] == 'high' else '🟡'} {t['title']}{due}")
        else:
            st.info("No pending tasks. Add some in the Revision Tracker.")
        st.subheader("Saved notes")
        if notes:
            for n in notes:
                st.write(f"📝 **{n['title'] or '(untitled)'}** — {(n['body'] or '')[:80]}")
        else:
            st.info("No notes yet.")
        st.subheader("Recent analysis reports")
        if jobs:
            for j in jobs:
                st.write(f"📊 {j['kind']} — {j['created_at'][:16]}")
        else:
            st.info("No analyses yet. Try the Accounting Workbench.")


# ================================================================ STUDY COACH

def _study_subjects_ui():
    st.subheader("Subjects & topics")
    subjects = revision.list_subjects(conn=conn)
    with st.expander("➕ Add subject / topic", expanded=not subjects):
        name = st.text_input("Subject name (e.g. CAF-1 Financial Accounting and Reporting I)",
                             key="new_subject")
        session = st.text_input("Exam session (e.g. Spring 2027)", key="new_session")
        if st.button("Add subject") and name.strip():
            revision.get_or_create_subject(name.strip(), exam_session=session.strip(), conn=conn)
            st.rerun()
        if subjects:
            s = st.selectbox("Subject", [x["name"] for x in subjects], key="topic_subject")
            tname = st.text_input("New topic name", key="new_topic")
            if st.button("Add topic") and tname.strip():
                sid = next(x["id"] for x in subjects if x["name"] == s)
                revision.get_or_create_topic(sid, tname.strip(), conn=conn)
                st.rerun()
    return subjects


def _doc_selector(label="Study from these documents (empty = all)", key="study_docs"):
    docs = documents.list_documents(conn=conn)
    options = {f"{d['filename']} [{d['status']}]": d["id"] for d in docs
               if d["status"] in ("indexed", "needs_ocr")}
    chosen = st.multiselect(label, list(options.keys()), key=key)
    return [options[c] for c in chosen] or None


def _render_answer(ans: "study.StudyAnswer"):
    if ans.notice:
        st.warning(ans.notice)
    st.markdown(ans.answer)
    if ans.sources:
        with st.expander(f"📎 Sources ({len(ans.sources)})", expanded=False):
            for s in ans.sources:
                st.markdown(f"**{study.citation_label(s)}**")
                st.caption(s.excerpt[:600])
    if not ans.ai_used:
        st.caption("Answered without AI (model unavailable) — passages shown directly.")


def _get_or_create_chat(title: str) -> int:
    row = conn.execute("SELECT id FROM chats ORDER BY updated_at DESC LIMIT 1").fetchone()
    if row:
        return row["id"]
    with db.transaction(conn) as cur:
        cur.execute("INSERT INTO chats(title) VALUES (?)", (title,))
        return cur.lastrowid


def show_study():
    st.header("Study Coach")
    st.caption("Answers are grounded in YOUR documents, with citations. "
               "Generated questions are practice only — never official ICAP material.")

    subjects = _study_subjects_ui()
    doc_ids = _doc_selector()

    tab_qa, tab_mcq, tab_progress = st.tabs(["❓ Ask", "✍️ Practice questions", "📈 Progress"])

    with tab_qa:
        chat_id = _get_or_create_chat("Study chat")
        history = conn.execute(
            "SELECT role, content FROM chat_messages WHERE chat_id = ? ORDER BY id",
            (chat_id,)).fetchall()
        for m in history[-20:]:
            with st.chat_message(m["role"]):
                st.markdown(m["content"][:2000])
        simple = st.checkbox("Explain in simple words", value=False)
        q = st.chat_input("Ask about your study material…")
        if q:
            with st.chat_message("user"):
                st.markdown(q)
            with db.transaction(conn) as cur:
                cur.execute("INSERT INTO chat_messages(chat_id, role, content) VALUES (?,?,?)",
                            (chat_id, "user", q))
            with st.chat_message("assistant"):
                with st.spinner("Searching your documents…"):
                    ans = (study.explain_simply if simple else study.ask)(
                        q, document_ids=doc_ids, settings=settings, conn=conn)
                _render_answer(ans)
            with db.transaction(conn) as cur:
                cur.execute(
                    "INSERT INTO chat_messages(chat_id, role, content, sources_json) VALUES (?,?,?,?)",
                    (chat_id, "assistant", ans.answer,
                     __import__("json").dumps([study.citation_label(s) for s in ans.sources])))
                cur.execute("UPDATE chats SET updated_at = datetime('now') WHERE id = ?",
                            (chat_id,))

    with tab_mcq:
        topic = st.text_input("Topic for practice questions", key="mcq_topic",
                              placeholder="e.g. IAS 2 inventory measurement")
        n = st.slider("Number of questions", 1, 10, 5)
        if st.button("Generate practice questions") and topic.strip():
            with st.spinner("Generating from your documents…"):
                out = study.generate_mcqs(topic.strip(), n=n, document_ids=doc_ids,
                                          settings=settings, conn=conn)
            if not out["ok"]:
                st.error(out["error"])
            else:
                st.caption(out["disclaimer"])
                st.session_state["mcqs"] = out["questions"]
                st.session_state["mcq_topic"] = topic.strip()
        for i, mcq in enumerate(st.session_state.get("mcqs", [])):
            with st.container(border=True):
                st.markdown(f"**Q{i+1}. {mcq['question']}**")
                choice = st.radio("Choose:", mcq["options"], key=f"mcq_{i}",
                                  index=None)
                if st.button(f"Check answer", key=f"mcq_check_{i}") and choice:
                    idx = mcq["options"].index(choice)
                    letter = "ABCD"[idx]
                    correct = study.grade_mcq(letter, mcq["answer"])
                    if correct:
                        st.success("Correct ✅")
                    else:
                        st.error(f"Not quite. Correct answer: {mcq['answer']}")
                    st.info(mcq.get("explanation", ""))
                    # record attempt against matching topic if one exists
                    tid = None
                    for s in subjects:
                        for t in revision.list_topics(s["id"], conn=conn):
                            if t["name"].lower() in st.session_state["mcq_topic"].lower():
                                tid = t["id"]
                    study.record_attempt(topic_id=tid, question_type="mcq",
                                         question_text=mcq["question"],
                                         options=mcq["options"],
                                         correct_answer=mcq["answer"],
                                         user_answer=letter, is_correct=correct,
                                         feedback=mcq.get("explanation", ""), conn=conn)

    with tab_progress:
        weak = study.weak_topics(conn=conn)
        st.subheader("Weak topics (accuracy < 60%, ≥3 attempts)")
        if weak:
            for w in weak:
                st.write(f"🔻 **{w['topic']}** ({w['subject']}) — "
                         f"{w['accuracy']:.0%} over {w['attempts']} attempts")
                if st.button(f"➕ Add revision task", key=f"weak_{w['id']}"):
                    revision.add_task(f"Revise {w['topic']}",
                                      subject_id=None, topic_id=w["id"],
                                      priority="high", conn=conn)
                    st.success("Task added.")
        else:
            st.info("Not enough graded attempts yet to identify weak topics.")
        st.subheader("Attempt history")
        hist = study.attempt_history(limit=30, conn=conn)
        if hist:
            import pandas as pd
            df = pd.DataFrame([{
                "When": h["attempted_at"][:16], "Topic": h["topic"] or "—",
                "Type": h["question_type"],
                "Question": (h["question_text"] or "")[:60],
                "Result": ("✅" if h["is_correct"] == 1 else
                           "❌" if h["is_correct"] == 0 else "—"),
            } for h in hist])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No attempts recorded yet.")


# ================================================================ DOCUMENT LIBRARY

def show_library():
    st.header("Document Library")
    st.caption("Files are copied into your local data folder — originals are never modified. "
               + PRIVACY_BADGE)

    with st.expander("⬆️ Import files", expanded=True):
        uploads = st.file_uploader(
            "PDF, DOCX, TXT, Markdown, CSV, XLSX",
            type=["pdf", "docx", "txt", "md", "csv", "xlsx"],
            accept_multiple_files=True)
        note = st.text_input("Provenance note (optional, e.g. 'CAF-1 study pack')",
                             key="import_note")
        if uploads and st.button("Import"):
            tmp = paths.data_dir() / "uploads"
            tmp.mkdir(exist_ok=True)
            for up in uploads:
                dest = tmp / up.name
                dest.write_bytes(up.getbuffer())
                res = documents.import_file(
                    dest, source_note=note,
                    ocr_enabled=settings["ocr"]["enabled"],
                    tesseract_cmd=settings["ocr"]["tesseract_cmd"],
                    ocr_dpi=settings["ocr"]["dpi"],
                    chunk_chars=settings["retrieval"]["chunk_chars"],
                    overlap_chars=settings["retrieval"]["chunk_overlap_chars"],
                    conn=conn)
                dest.unlink(missing_ok=True)
                if res.status == "indexed":
                    st.success(f"✅ {up.name}: {res.message}")
                elif res.status == "duplicate":
                    st.info(f"ℹ️ {up.name}: {res.message}")
                elif res.status == "needs_ocr":
                    st.warning(f"⚠️ {up.name}: {res.message}")
                else:
                    st.error(f"❌ {up.name}: {res.message}")
            st.rerun()

    st.subheader("🔍 Search")
    q = st.text_input("Keyword search across all indexed documents", key="lib_search")
    if q.strip():
        hits = documents.search(q.strip(), limit=30, conn=conn)
        if not hits:
            st.info("No matches. Try different keywords.")
        for h in hits[:15]:
            loc = h["filename"]
            if h["page_number"]:
                loc += f", p.{h['page_number']}"
            if h["section"]:
                loc += f" [{h['section']}]"
            with st.container(border=True):
                st.markdown(f"**{loc}**")
                st.caption(h["snippet"].replace("[", "**").replace("]", "**"))

    st.subheader("All documents")
    docs = documents.list_documents(conn=conn)
    if not docs:
        st.info("Library is empty.")
    for d in docs:
        icon = {"pdf": "📕", "docx": "📘", "xlsx": "📊", "csv": "📄"}.get(d["file_type"], "📄")
        status_emoji = {"indexed": "✅", "needs_ocr": "⚠️",
                        "failed": "❌", "unsupported": "⛔"}.get(d["status"], "❓")
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"{icon} **{d['filename']}** {status_emoji} `{d['status']}`")
                st.caption(f"{d['chunks']} indexed passages · "
                           f"imported {d['imported_at'][:16]}"
                           + (f" · {d['page_count']} pages" if d["page_count"] else "")
                           + (f" · OCR used" if d["ocr_used"] else ""))
                if d["error"]:
                    st.warning(d["error"])
            with c2:
                if st.button("Preview", key=f"pv_{d['id']}"):
                    st.session_state[f"show_pv_{d['id']}"] = True
                if st.button("Delete", key=f"del_{d['id']}"):
                    if documents.delete_document(d["id"], conn=conn):
                        st.success("Deleted.")
                        st.rerun()
            if st.session_state.get(f"show_pv_{d['id']}"):
                st.text_area("Extracted text preview", documents.preview_text(d["id"], conn=conn),
                             height=220, key=f"pvtxt_{d['id']}", disabled=True)
            # link to subject/topic
            subjects = revision.list_subjects(conn=conn)
            if subjects:
                key = f"link_{d['id']}"
                sel = st.selectbox("Link to subject", ["—"] + [s["name"] for s in subjects],
                                   key=key)
                if sel != "—":
                    sid = next(s["id"] for s in subjects if s["name"] == sel)
                    with db.transaction(conn) as cur:
                        cur.execute(
                            "INSERT OR IGNORE INTO doc_subjects(document_id, subject_id)"
                            " VALUES (?, ?)", (d["id"], sid))
                    st.caption(f"Linked to {sel}.")


# ================================================================ WORKBENCH

def _upload_table(label: str, key: str):
    up = st.file_uploader(label, type=["csv", "xlsx"], key=key)
    if not up:
        return None, None
    tmp = paths.data_dir() / "uploads"
    tmp.mkdir(exist_ok=True)
    dest = tmp / up.name
    dest.write_bytes(up.getbuffer())
    if dest.suffix.lower() == ".xlsx":
        sheets = wb.sheet_names(dest)
        sheet = st.selectbox(f"Sheet ({up.name})", sheets, key=key + "_sheet") \
            if len(sheets) > 1 else sheets[0]
    else:
        sheet = 0
    try:
        df = wb.load_table(dest, sheet=sheet)
    except Exception as exc:
        st.error(f"Could not read {up.name}: {exc}")
        return None, None
    return df, up.name


def _record_job(kind: str, sources: list, settings_used: dict, summary: dict):
    import json
    with db.transaction(conn) as cur:
        cur.execute(
            """INSERT INTO analysis_jobs(kind, source_files_json, settings_json, summary_json)
               VALUES (?, ?, ?, ?)""",
            (kind, json.dumps(sources), json.dumps(settings_used), json.dumps(summary)))
        return cur.lastrowid


def _export_ui(findings_df, summary: dict, job_id: int, base: str):
    import pandas as pd
    c1, c2 = st.columns(2)
    for fmt, col in (("xlsx", c1), ("csv", c2)):
        path = wb.export_report(findings_df, paths.reports_dir() / f"{base}.{fmt}",
                                fmt=fmt, summary=summary)
        with db.transaction(conn) as cur:
            cur.execute("INSERT INTO report_files(job_id, path, format) VALUES (?,?,?)",
                        (job_id, path.name, fmt))
        with open(path, "rb") as fh:
            col.download_button(f"⬇️ Download {fmt.upper()}", fh,
                                file_name=path.name, key=f"dl_{base}_{fmt}")


def show_workbench():
    st.header("Accounting Workbench")
    st.caption("Deterministic analysis — every figure is computed by tested Python code, "
               "never by the AI. Uploads stay on this computer.")
    st.warning("⚠️ Outputs are drafts for human review, not final professional conclusions.",
               icon="⚠️")

    tab_insp, tab_dup, tab_rec, tab_val, tab_hist = st.tabs(
        ["🔎 Inspect", "👯 Duplicates", "⚖️ Reconcile", "✔️ Validate", "🗂️ History"])

    with tab_insp:
        df, name = _upload_table("Upload CSV or XLSX", "insp_up")
        if df is not None:
            info = wb.inspect_table(df, name)
            st.write(f"**{info['rows']}** rows")
            import pandas as pd
            st.dataframe(pd.DataFrame(info["columns"]), use_container_width=True,
                         hide_index=True)
            st.subheader("First rows")
            st.dataframe(df.drop(columns=["_src_row"]).head(20), use_container_width=True,
                         hide_index=True)
            _record_job("inspection", [{"filename": name}], {}, info)

    with tab_dup:
        df, name = _upload_table("Upload CSV or XLSX", "dup_up")
        if df is not None:
            cols = [c for c in df.columns if c != "_src_row"]
            chosen = st.multiselect("Match on columns (e.g. InvoiceNo, or InvoiceNo+Date)",
                                    cols, default=[cols[0]] if cols else [], key="dup_cols")
            if st.button("Find duplicates") and chosen:
                findings = wb.find_duplicates(df, chosen)
                _record_job("duplicates", [{"filename": name}],
                            {"columns": chosen},
                            {"groups": len(findings),
                             "rows": sum(f.details["count"] for f in findings)})
                if not findings:
                    st.success("No duplicates found on the selected columns.")
                for f in findings:
                    with st.container(border=True):
                        st.error(f.message)
                        import pandas as pd
                        st.dataframe(pd.DataFrame(f.details["records"]),
                                     use_container_width=True, hide_index=True)
                if findings:
                    jid = conn.execute("SELECT MAX(id) FROM analysis_jobs").fetchone()[0]
                    _export_ui(findings, {"duplicate groups": len(findings)}, jid, "duplicates")

    with tab_rec:
        st.markdown("Match two datasets (e.g. bank statement vs cash book) on a shared ID.")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Dataset A**")
            df_a, name_a = _upload_table("File A", "rec_a")
        with c2:
            st.markdown("**Dataset B**")
            df_b, name_b = _upload_table("File B", "rec_b")
        tol = st.number_input("Amount tolerance", value=float(
            settings["reconciliation"]["amount_tolerance"]), min_value=0.0, step=0.01)
        if df_a is not None and df_b is not None:
            cols_a = [c for c in df_a.columns if c != "_src_row"]
            cols_b = [c for c in df_b.columns if c != "_src_row"]
            m1, m2, m3, m4 = st.columns(4)
            id_a = m1.selectbox("A: ID column", cols_a, key="ra_id")
            amt_a = m2.selectbox("A: Amount column", cols_a, key="ra_amt")
            id_b = m3.selectbox("B: ID column", cols_b, key="rb_id")
            amt_b = m4.selectbox("B: Amount column", cols_b, key="rb_amt")
            if st.button("Run reconciliation"):
                result = wb.reconcile(
                    df_a, df_b,
                    ColumnMap(id=id_a, amount=amt_a),
                    ColumnMap(id=id_b, amount=amt_b),
                    amount_tolerance=tol, label_a=name_a or "A", label_b=name_b or "B")
                s = result["summary"]
                jid = _record_job("reconciliation",
                                  [{"filename": name_a}, {"filename": name_b}],
                                  {"id_a": id_a, "amount_a": amt_a, "id_b": id_b,
                                   "amount_b": amt_b, "tolerance": tol}, s)
                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Matched", s["matched"])
                k2.metric("Amount diffs", s["amount_differences"])
                k3.metric(f"Only in A", s["unmatched_a"])
                k4.metric(f"Only in B", s["unmatched_b"])
                k5.metric("Ambiguous IDs", s["ambiguous_ids"])
                import pandas as pd

                def _rows(recs):
                    return pd.DataFrame([{
                        "Row": r["row_ref"], "ID": r["id"], "Amount": r["amount"],
                        "Date": r["date"], "Description": r["desc"][:60]} for r in recs])

                with st.expander(f"⚠️ Amount differences ({len(result['amount_differences'])})"):
                    for d in result["amount_differences"]:
                        st.write(f"**{d['id']}**: A={d['a']['amount']} vs "
                                 f"B={d['b']['amount']} (diff {d.get('difference', '?')}) "
                                 f"— rows A:{d['a']['row_ref']} B:{d['b']['row_ref']}")
                with st.expander(f"Unmatched in A ({len(result['unmatched_a'])})"):
                    if result["unmatched_a"]:
                        st.dataframe(_rows(result["unmatched_a"]), hide_index=True,
                                     use_container_width=True)
                with st.expander(f"Unmatched in B ({len(result['unmatched_b'])})"):
                    if result["unmatched_b"]:
                        st.dataframe(_rows(result["unmatched_b"]), hide_index=True,
                                     use_container_width=True)
                with st.expander(f"🟠 Ambiguous — needs human review ({len(result['ambiguous'])})"):
                    for a in result["ambiguous"]:
                        st.warning(f"**{a['id']}**: A rows {a['side_a_rows']}, "
                                   f"B rows {a['side_b_rows']}. {a['note']}")
                if result["blank_ids_a"] or result["blank_ids_b"]:
                    st.info(f"Blank IDs: {len(result['blank_ids_a'])} in A, "
                            f"{len(result['blank_ids_b'])} in B.")
                if result["suggestions"]:
                    with st.expander(f"💡 Possible matches — review required "
                                     f"({len(result['suggestions'])})"):
                        for sg in result["suggestions"]:
                            st.write(f"A row {sg['a_row']} ({sg['a_id']}) might match: "
                                     + "; ".join(
                                         f"B row {c['b_row']} ({c['b_id']}, {c['amount']})"
                                         for c in sg["candidates"]))
                # export a flat findings file
                flat = []
                for d in result["amount_differences"]:
                    flat.append({"kind": "amount_difference", "severity": "error",
                                 "message": f"{d['id']}: A={d['a']['amount']} B={d['b']['amount']}",
                                 "row_ref": d["a"]["row_ref"], "column": None, "details": ""})
                for r in result["unmatched_a"]:
                    flat.append({"kind": "unmatched_a", "severity": "warning",
                                 "message": f"{r['id']} only in A (amount {r['amount']})",
                                 "row_ref": r["row_ref"], "column": None, "details": ""})
                for r in result["unmatched_b"]:
                    flat.append({"kind": "unmatched_b", "severity": "warning",
                                 "message": f"{r['id']} only in B (amount {r['amount']})",
                                 "row_ref": r["row_ref"], "column": None, "details": ""})
                for a in result["ambiguous"]:
                    flat.append({"kind": "ambiguous", "severity": "error",
                                 "message": f"{a['id']}: duplicated ID — manual review",
                                 "row_ref": None, "column": None, "details": str(a)})
                import pandas as pd
                _export_ui(pd.DataFrame(flat), s, jid, "reconciliation")

    with tab_val:
        df, name = _upload_table("Upload CSV or XLSX", "val_up")
        if df is not None:
            cols = [c for c in df.columns if c != "_src_row"]
            req = st.multiselect("Required columns (blank = error)", cols, key="v_req")
            dtc = st.multiselect("Date columns", cols, key="v_dt")
            amt = st.multiselect("Amount columns", cols, key="v_amt")
            nn = st.multiselect("Must be non-negative", cols, key="v_nn")
            if st.button("Run validation"):
                rules = ValidationRules(required_columns=req, date_columns=dtc,
                                        amount_columns=amt, non_negative_columns=nn)
                findings = wb.validate_table(df, rules, name)
                jid = _record_job("validation", [{"filename": name}],
                                  {"required": req, "dates": dtc, "amounts": amt},
                                  {"findings": len(findings)})
                sev = st.multiselect("Severity", ["error", "warning", "info"],
                                     default=["error", "warning", "info"])
                shown = [f for f in findings if f.severity in sev]
                st.write(f"**{len(shown)}** finding(s)")
                for f in shown:
                    icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}[f.severity]
                    st.write(f"{icon} **[{f.kind}]** {f.message}"
                             + (f" (row {f.row_ref})" if f.row_ref else ""))
                if findings:
                    _export_ui(findings, {"findings": len(findings)}, jid, "validation")
                else:
                    st.success("All checks passed.")

    with tab_hist:
        jobs = conn.execute(
            "SELECT * FROM analysis_jobs ORDER BY created_at DESC LIMIT 20").fetchall()
        if not jobs:
            st.info("No analyses recorded yet.")
        for j in jobs:
            import json
            with st.expander(f"{j['kind']} — {j['created_at'][:16]}"):
                st.json(json.loads(j["summary_json"]))
                files = conn.execute("SELECT * FROM report_files WHERE job_id = ?",
                                     (j["id"],)).fetchall()
                for rf in files:
                    p = paths.reports_dir() / rf["path"]
                    if p.exists():
                        with open(p, "rb") as fh:
                            st.download_button(f"⬇️ {rf['path']}", fh,
                                               file_name=rf["path"],
                                               key=f"hist_{rf['id']}")


# ================================================================ REVISION TRACKER

def show_revision():
    st.header("Revision Tracker")
    st.caption("Tasks, notes, and bookmarks — all stored locally.")

    tab_tasks, tab_notes = st.tabs(["✅ Tasks", "📝 Notes & bookmarks"])

    with tab_tasks:
        with st.expander("➕ Add revision task", expanded=True):
            title = st.text_input("Task", placeholder="e.g. Revise IAS 2 NRV workings")
            c1, c2, c3 = st.columns(3)
            due = c1.text_input("Due date (YYYY-MM-DD)", placeholder="2026-11-01")
            prio = c2.selectbox("Priority", ["low", "medium", "high"], index=1)
            subjects = revision.list_subjects(conn=conn)
            subj = c3.selectbox("Subject (optional)", ["—"] + [s["name"] for s in subjects])
            if st.button("Add task") and title.strip():
                sid = None
                if subj != "—":
                    sid = next(s["id"] for s in subjects if s["name"] == subj)
                if due.strip():
                    try:
                        date.fromisoformat(due.strip())
                    except ValueError:
                        st.error("Due date must be YYYY-MM-DD.")
                        st.stop()
                revision.add_task(title.strip(), subject_id=sid,
                                  due_date=due.strip(), priority=prio, conn=conn)
                st.success("Task added.")
                st.rerun()
        show_done = st.checkbox("Show completed", value=False)
        tasks = revision.list_tasks(conn=conn)
        if not show_done:
            tasks = [t for t in tasks if t["status"] == "pending"]
        today = date.today().isoformat()
        for t in tasks:
            overdue = t["status"] == "pending" and t["due_date"] and t["due_date"] < today
            with st.container(border=True):
                c1, c2, c3 = st.columns([5, 1, 1])
                with c1:
                    mark = "✅" if t["status"] == "done" else ("🔴" if overdue else "⬜")
                    st.markdown(f"{mark} **{t['title']}**")
                    st.caption(
                        f"{t['subject'] or 'No subject'} · priority {t['priority']}"
                        + (f" · due {t['due_date']}" + (" — OVERDUE" if overdue else "")
                           if t["due_date"] else ""))
                with c2:
                    if t["status"] == "pending" and st.button("Done", key=f"done_{t['id']}"):
                        revision.complete_task(t["id"], conn=conn)
                        st.rerun()
                with c3:
                    if st.button("Delete", key=f"tdel_{t['id']}"):
                        revision.delete_task(t["id"], conn=conn)
                        st.rerun()

    with tab_notes:
        with st.expander("➕ New note / bookmark", expanded=True):
            ntitle = st.text_input("Title", key="note_title")
            nbody = st.text_area("Body", key="note_body", height=120)
            is_bm = st.checkbox("Save as bookmark ⭐", key="note_bm")
            if st.button("Save note") and (ntitle.strip() or nbody.strip()):
                revision.save_note(ntitle.strip(), nbody, is_bookmark=is_bm, conn=conn)
                st.success("Note saved.")
                st.rerun()
        only_bm = st.checkbox("Bookmarks only", value=False)
        for n in revision.list_notes(bookmarks_only=only_bm, conn=conn):
            with st.container(border=True):
                st.markdown(f"{'⭐ ' if n['is_bookmark'] else '📝 '}"
                            f"**{n['title'] or '(untitled)'}**")
                st.caption(f"{n['updated_at'][:16]}"
                           + (f" · from {n['document_name']}" if n["document_name"] else ""))
                st.write(n["body"][:500])
                if st.button("Delete", key=f"ndel_{n['id']}"):
                    revision.delete_note(n["id"], conn=conn)
                    st.rerun()


# ================================================================ SETTINGS & DIAGNOSTICS

def show_settings():
    st.header("Settings & Diagnostics")
    st.caption(PRIVACY_BADGE)

    st.subheader("🤖 Local AI (Ollama)")
    st_ = ai.get_status(settings)
    if st_.reachable and st_.active_model in st_.models:
        st.success(f"Ready — {st_.active_model}")
    else:
        st.warning(st_.message)
        st.info("Without a model, keyword search and all workbench tools still work. "
                "To enable AI: install Ollama from https://ollama.com, then run "
                f"`ollama pull {settings['ai']['model']}` (small models suit 8 GB RAM).")
    c1, c2 = st.columns(2)
    with c1:
        if st_.models:
            model = st.selectbox("Model", st_.models,
                                 index=st_.models.index(st_.active_model)
                                 if st_.active_model in st_.models else 0)
        else:
            model = st.text_input("Model", value=settings["ai"]["model"])
        timeout = st.number_input("Request timeout (seconds)",
                                  value=settings["ai"]["timeout_seconds"], min_value=10)
    with c2:
        ctx = st.number_input("Max context chars (retrieved text)",
                              value=settings["ai"]["max_context_chars"], min_value=1000)
        topk = st.number_input("Retrieval: passages per answer",
                               value=settings["retrieval"]["top_k"], min_value=1, max_value=10)
    if st.button("Save AI settings"):
        settings["ai"]["model"] = model
        settings["ai"]["timeout_seconds"] = int(timeout)
        settings["ai"]["max_context_chars"] = int(ctx)
        settings["retrieval"]["top_k"] = int(topk)
        config.save(settings)
        st.success("Saved. The model is never downloaded automatically.")

    st.subheader("🔍 OCR (scanned PDFs)")
    st.caption("Optional and off by default. Needs Tesseract-OCR installed separately.")
    ocr_on = st.checkbox("Enable OCR for scanned PDFs", value=settings["ocr"]["enabled"])
    tess = st.text_input("Tesseract command (empty = auto-detect)",
                         value=settings["ocr"]["tesseract_cmd"])
    if st.button("Save OCR settings"):
        settings["ocr"]["enabled"] = bool(ocr_on)
        settings["ocr"]["tesseract_cmd"] = tess.strip()
        config.save(settings)
        st.success("Saved.")

    st.subheader("💾 Data, backup & restore")
    st.code(str(paths.data_dir()))
    st.caption("All documents, chats, notes, tasks, and reports live here. "
               "Copy this folder to back up everything manually.")
    if st.button("Create backup now"):
        zf = backup.create_backup()
        st.success(f"Backup created: {zf.name}")
    ups = backup.list_backups()
    if ups:
        st.write("Existing backups:")
        for b in ups[:10]:
            info = backup.inspect_backup(b)
            st.write(f"📦 {b.name} — {info['size_bytes'] // 1024} KB, "
                     f"{info['files']} files")
    with st.expander("Restore from backup"):
        st.warning("Restore extracts into an EMPTY folder you choose — it never "
                   "merges into live data.")
        target = st.text_input("Empty target folder",
                               placeholder="e.g. C:\\CA-Copilot-Restore")
        src = st.selectbox("Backup file", [str(b) for b in ups] if ups else [])
        if st.button("Restore") and target and src:
            try:
                out = backup.restore_backup(Path(src), Path(target))
                st.success(f"Restored to {out}. Point CA_COPILOT_DATA_DIR at it, "
                           "or replace your data folder after taking a fresh backup.")
            except ValueError as exc:
                st.error(str(exc))

    st.subheader("🔒 Privacy & connectivity")
    st.info(
        "• The app binds to **127.0.0.1 only** — no LAN or internet access.\n"
        "• **No telemetry, analytics, or cloud uploads.**\n"
        "• The AI provider must always be a localhost runtime — the app refuses "
        "non-local AI hosts.\n"
        "• Document text is treated as untrusted data and never as instructions.\n"
        "• Personal use only: **firm authorization and proper confidentiality "
        "controls are required before using any client information.**")
    st.subheader("🧾 Tax & professional safeguards")
    st.info(tax_rules.TAX_NOT_READY_MESSAGE)
    st.caption("Accounting and audit outputs are drafts for human review, "
               "not final professional conclusions.")

    st.subheader("📋 Known limitations")
    st.markdown(
        "- OCR needs Tesseract-OCR installed separately and is off by default.\n"
        "- Keyword search (FTS5), not semantic search — use the document's own wording.\n"
        "- qwen3:1.7b is a small model: good for explanations, weak at long "
        "multi-step arithmetic — use the Workbench for calculations.\n"
        "- Reconciliation matches on exact IDs; fuzzy/ML matching is not included.\n"
        "- First release: no tax computation module (framework only).")


# ================================================================ dispatch

{"Dashboard": show_dashboard,
 "Study Coach": show_study,
 "Document Library": show_library,
 "Accounting Workbench": show_workbench,
 "Revision Tracker": show_revision,
 "Settings & Diagnostics": show_settings}[section]()
