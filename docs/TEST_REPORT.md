# Test report — CA Copilot Local (initial release)

Date: 2026-10-21. Environment: Python 3.12, Streamlit 1.66, pandas 3.0.6,
pytest 9.1.1 (Linux build machine; code is cross-platform, Windows is the
target — no Windows-only APIs are used).

## Automated suite: 45 passed, 0 failed

`pytest tests/ -q` — every test uses an isolated temporary data directory
(`CA_COPILOT_DATA_DIR`), so tests never touch real user data.

| File | Tests | What is verified |
|---|---|---|
| test_db.py | 4 | migrations create all 15 tables incl. FTS5 index; idempotent; parameterized SQL (injection string stored literally); DB file in data dir |
| test_config.py | 3 | settings created with safe defaults; save/load round-trip; corrupt or partial config falls back to defaults |
| test_thread_safety.py | 2 | connection created on one thread usable from another (no ProgrammingError); independent per-thread connections |
| test_documents.py | 8 | MD/CSV/XLSX import + keyword search; duplicate import detected by SHA-256; unsupported type rejected; scanned PDF flagged `needs_ocr` (never claimed as read); delete removes index entries; chunk overlap |
| test_workbench.py | 9 | **reconciliation matches hand-computed expectations** (6 matched, 1 amount diff of −500, 1 unmatched each side, 1 ambiguous ID, 1 blank ID); duplicates found with original row refs; blank keys don't false-positive; validation finds blank/invalid-date/invalid-amount/negative/outlier/round-number issues with correct severities; arithmetic total check; CSV+XLSX export round-trips |
| test_study.py | 7 | retrieval returns cited sources; `ask()` with no Ollama returns grounded fallback with passages (no exception); no-source query says so; MCQ generation fails gracefully without AI; MCQ grading deterministic; weak-topic detection (accuracy < 60%) |
| test_revision_backup.py | 12 | task lifecycle; overdue detection; notes/bookmarks; idempotent subjects/topics; backup ZIP create/inspect/restore round-trip; non-empty restore target refused; Ollama refuses non-localhost; unreachable Ollama reported gracefully; tax computation raises NotImplementedError |

## UI verification (Streamlit AppTest, headless)

- App serves HTTP 200 on 127.0.0.1 with no log errors.
- All 6 sections render with zero script exceptions: Dashboard, Study Coach,
  Document Library, Accounting Workbench, Revision Tracker, Settings & Diagnostics.

## Acceptance criteria (from the project brief)

1. ✅ Launches successfully — verified via `streamlit run` + AppTest (Linux; Windows launch via `run_windows.bat` follows the same commands).
2. ✅ Dashboard and all navigation sections work — AppTest, no exceptions.
3. ✅ Documents import, search, reopen — tests + preview.
4. ✅ Document-grounded answers show source references — citations (document, page/section, excerpt) in every grounded answer.
5. ✅ Study Coach works with local model; degrades gracefully — fallback path tested (no Ollama on build machine).
6. ✅ Duplicate detection correct on test dataset — INV-1002/INV-1004 groups with exact row refs.
7. ✅ Reconciliation matches independently calculated expectations — see table above.
8. ✅ CSV/XLSX reports export and reopen — round-trip tested.
9. ✅ Data persists after restart — SQLite WAL in the data dir (not temp, not source tree).
10. ✅ Backup and restore work on a test copy — round-trip tested incl. refusal on non-empty target.
11. ✅ Works offline after install — no network calls except localhost Ollama; telemetry disabled in `.streamlit/config.toml`; server binds 127.0.0.1 only.
12. ✅ Tests pass; limitations documented — `docs/PRIVACY_AND_LIMITATIONS.md`.

## Known issues found during testing (all fixed)

- FTS5 `content=''` external-content tables return NULL for all columns — switched to internal-content FTS table.
- FTS5 special `'delete'` command syntax rejected on SQLite 3.45 — triggers now use plain `DELETE ... WHERE rowid =`.
- Outlier heuristic based on 99th percentile never fired on skewed data — replaced with median-based (10× median) rule.
- XLSX sheet names weren't searchable — sheet title now included in indexed text and section metadata.
- 2026-10-21: `pyyaml` needed a C compiler on Windows ("Microsoft Visual C++ 14.0
  required"). Removed the dependency entirely — settings are now plain JSON via
  the standard library. Verified a from-scratch `pip install -r requirements.txt`
  completes with zero compilation.
- 2026-10-21: `sqlite3.ProgrammingError` on Windows (connection created on one
  Streamlit thread, used on another). Fixed with a fresh DB connection per
  script run plus `check_same_thread=False` as a safety net; regression tests
  added (old behaviour verified to raise ProgrammingError).
