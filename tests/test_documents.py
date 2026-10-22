"""Tests for document import, search, preview, and duplicate handling."""

from ca_copilot import db, documents, extractors


def test_import_markdown_and_search(sample_data):
    conn = db.get_db()
    try:
        res = documents.import_file(sample_data / "study_ias2_summary.md", conn=conn)
        assert res.status == "indexed", res.message
        assert res.document_id is not None

        hits = documents.search("net realisable value", conn=conn)
        assert hits, "FTS search should find the IAS 2 summary"
        assert any("study_ias2_summary" in h["filename"] for h in hits)

        preview = documents.preview_text(res.document_id, conn=conn)
        assert "lower of cost and net realisable value" in preview.lower()
    finally:
        conn.close()


def test_duplicate_import_detected(sample_data):
    conn = db.get_db()
    try:
        first = documents.import_file(sample_data / "study_ias2_summary.md", conn=conn)
        second = documents.import_file(sample_data / "study_ias2_summary.md", conn=conn)
        assert first.status == "indexed"
        assert second.status == "duplicate"
        assert second.document_id == first.document_id
        docs = documents.list_documents(conn=conn)
        assert len(docs) == 1
    finally:
        conn.close()


def test_unsupported_file_type(tmp_path):
    conn = db.get_db()
    try:
        weird = tmp_path / "notes.xyz"
        weird.write_text("hello")
        res = documents.import_file(weird, conn=conn)
        assert res.status == "unsupported"
        assert res.document_id is None
    finally:
        conn.close()


def test_csv_import_and_search(sample_data):
    conn = db.get_db()
    try:
        res = documents.import_file(sample_data / "bank_statement.csv", conn=conn)
        assert res.status == "indexed", res.message
        hits = documents.search("TXN-003", conn=conn)
        assert hits
    finally:
        conn.close()


def test_xlsx_import(tmp_path):
    import openpyxl
    p = tmp_path / "sheet.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TrialBalance"
    ws.append(["Account", "Debit", "Credit"])
    ws.append(["Cash", 1000, 0])
    wb.save(p)
    conn = db.get_db()
    try:
        res = documents.import_file(p, conn=conn)
        assert res.status == "indexed", res.message
        hits = documents.search("TrialBalance", conn=conn)
        assert hits and hits[0]["section"] == "TrialBalance"
    finally:
        conn.close()


def test_scanned_pdf_flagged_without_ocr(tmp_path):
    from pypdf import PdfWriter
    p = tmp_path / "scanned.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)  # no text -> looks scanned
    with open(p, "wb") as fh:
        w.write(fh)
    conn = db.get_db()
    try:
        res = documents.import_file(p, conn=conn)
        # Must NOT claim it was read: status reflects missing text.
        assert res.status == "needs_ocr", res.message
        doc = documents.get_document(res.document_id, conn=conn)
        assert doc is not None and doc["status"] == "needs_ocr"
        assert "scanned" in (doc["error"] or "").lower()
    finally:
        conn.close()


def test_delete_document(sample_data):
    conn = db.get_db()
    try:
        res = documents.import_file(sample_data / "study_ias2_summary.md", conn=conn)
        assert documents.delete_document(res.document_id, conn=conn)
        assert documents.get_document(res.document_id, conn=conn) is None
        assert documents.search("realisable", conn=conn) == []
    finally:
        conn.close()


def test_chunking_overlap():
    text = "para\n\n" * 400  # long text with paragraph breaks
    chunks = extractors.chunk_text(text, page=1, section=None,
                                   chunk_chars=1500, overlap_chars=200)
    assert len(chunks) > 1
    # overlap: end of one chunk appears in the next
    assert chunks[0][2][-50:] in chunks[1][2] or len(chunks[0][2]) < 1500
    for page, section, piece in chunks:
        assert len(piece) <= 1500
