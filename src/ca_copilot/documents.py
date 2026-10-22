"""Local document library: import, index, keyword search, previews.

- Imported files are COPIED into <data_dir>/documents/ (originals untouched).
- Duplicate imports are detected by SHA-256 and reported, not duplicated.
- Extracted text is chunked and indexed with SQLite FTS5 for keyword search.
- Nothing leaves the computer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, extractors, paths


@dataclass
class ImportResult:
    document_id: int | None
    filename: str
    status: str            # indexed | duplicate | needs_ocr | failed | unsupported
    message: str
    page_count: int | None = None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _store_copy(src: Path, digest: str, file_type: str) -> Path:
    dest_dir = paths.documents_dir()
    dest = dest_dir / f"{digest[:16]}_{src.stem[:60]}.{file_type}"
    if not dest.exists():
        shutil.copy2(src, dest)
    return dest.relative_to(dest_dir)


def import_file(src: Path, *, source_note: str = "",
                ocr_enabled: bool = False, tesseract_cmd: str = "",
                ocr_dpi: int = 200,
                chunk_chars: int = 1500, overlap_chars: int = 200,
                conn=None) -> ImportResult:
    """Import one file into the library. Returns an ImportResult (never raises)."""
    src = Path(src)
    if not src.is_file():
        return ImportResult(None, src.name, "failed", "File not found.")
    try:
        file_type = extractors.detect_type(src)
    except extractors.ExtractionError as exc:
        return ImportResult(None, src.name, "unsupported", str(exc))

    digest = sha256_of(src)
    own = conn is None
    conn = conn or db.get_db()
    try:
        existing = conn.execute(
            "SELECT id, filename FROM documents WHERE sha256 = ?", (digest,)
        ).fetchone()
        if existing:
            return ImportResult(existing["id"], src.name, "duplicate",
                                f"Already in library as '{existing['filename']}'.")

        try:
            extraction = extractors.extract(
                src, ocr_enabled=ocr_enabled, tesseract_cmd=tesseract_cmd, ocr_dpi=ocr_dpi
            )
        except extractors.ExtractionError as exc:
            return ImportResult(None, src.name, "failed", str(exc))

        stored_rel = _store_copy(src, digest, file_type)

        if not extraction.has_extractable_text:
            status = "needs_ocr"
            message = ("No readable text found. This looks like a scanned document — "
                       "enable OCR in Settings and re-import to attempt reading it.")
        else:
            status = "indexed"
            message = "Imported and indexed."
        if extraction.warnings:
            message += " " + " ".join(extraction.warnings)
            if any("scanned" in w for w in extraction.warnings):
                status = "needs_ocr" if not extraction.ocr_used else "indexed"

        with db.transaction(conn) as cur:
            cur.execute(
                """INSERT INTO documents
                   (filename, stored_path, file_type, file_size, sha256, page_count,
                    status, ocr_used, error, source_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (src.name, str(stored_rel), file_type, src.stat().st_size, digest,
                 extraction.page_count, status, int(extraction.ocr_used),
                 None if status == "indexed" else message, source_note or None),
            )
            doc_id = cur.lastrowid
            idx = 0
            for pt in extraction.pages:
                for (page, section, text) in extractors.chunk_text(
                        pt.text, page=pt.page, section=pt.section,
                        chunk_chars=chunk_chars, overlap_chars=overlap_chars):
                    cur.execute(
                        "INSERT INTO doc_chunks(document_id, chunk_index, page_number, section, text)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (doc_id, idx, page, section, text),
                    )
                    idx += 1
        return ImportResult(doc_id, src.name, status, message, extraction.page_count)
    finally:
        if own:
            conn.close()


def search(query: str, *, document_ids: list[int] | None = None,
           limit: int = 20, conn=None) -> list[dict[str, Any]]:
    """Keyword search over indexed chunks (FTS5). Returns chunks with citations."""
    query = query.strip()
    if not query:
        return []
    own = conn is None
    conn = conn or db.get_db()
    try:
        # Sanitize FTS5 query: quote each term to avoid syntax errors.
        terms = [t for t in query.split() if t]
        fts_q = " OR ".join(f'"{t}"' for t in terms) if terms else '""'
        sql = """
            SELECT f.chunk_id AS chunk_id, f.document_id AS document_id,
                   d.filename AS filename, c.page_number AS page_number,
                   c.section AS section,
                   snippet(doc_chunks_fts, 0, '[', ']', '…', 40) AS snippet
            FROM doc_chunks_fts f
            JOIN doc_chunks c ON c.id = f.chunk_id
            JOIN documents d ON d.id = f.document_id
            WHERE doc_chunks_fts MATCH ?
        """
        params: list[Any] = [fts_q]
        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            sql += f" AND f.document_id IN ({placeholders})"
            params.extend(document_ids)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_chunk_text(chunk_id: int, conn=None) -> dict[str, Any] | None:
    own = conn is None
    conn = conn or db.get_db()
    try:
        row = conn.execute(
            """SELECT c.id, c.document_id, c.page_number, c.section, c.text, d.filename
               FROM doc_chunks c JOIN documents d ON d.id = c.document_id
               WHERE c.id = ?""", (chunk_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def list_documents(conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or db.get_db()
    try:
        rows = conn.execute(
            """SELECT d.*, COUNT(c.id) AS chunks
               FROM documents d LEFT JOIN doc_chunks c ON c.document_id = d.id
               GROUP BY d.id ORDER BY d.imported_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_document(doc_id: int, conn=None) -> dict[str, Any] | None:
    own = conn is None
    conn = conn or db.get_db()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def preview_text(doc_id: int, *, max_chars: int = 4000, conn=None) -> str:
    """Extracted-text preview (first chunks) for quick reading."""
    own = conn is None
    conn = conn or db.get_db()
    try:
        rows = conn.execute(
            "SELECT page_number, section, text FROM doc_chunks WHERE document_id = ?"
            " ORDER BY chunk_index LIMIT 6", (doc_id,)).fetchall()
        parts = []
        for r in rows:
            label = []
            if r["page_number"]:
                label.append(f"p.{r['page_number']}")
            if r["section"]:
                label.append(str(r["section"]))
            head = f"[{' · '.join(label)}] " if label else ""
            parts.append(head + r["text"][:max_chars])
        text = "\n\n".join(parts)
        return text[:max_chars]
    finally:
        if own:
            conn.close()


def stored_file_path(doc: dict[str, Any]) -> Path:
    return paths.documents_dir() / doc["stored_path"]


def delete_document(doc_id: int, *, delete_file: bool = True, conn=None) -> bool:
    own = conn is None
    conn = conn or db.get_db()
    try:
        doc = get_document(doc_id, conn=conn)
        if not doc:
            return False
        with db.transaction(conn) as cur:
            cur.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        if delete_file:
            p = stored_file_path(doc)
            if p.exists():
                p.unlink()
        return True
    finally:
        if own:
            conn.close()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
