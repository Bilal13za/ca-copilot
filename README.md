# CA Copilot Local

A **local-first desktop app** for CA exam preparation (ICAP CAF) and practical
accounting work — document library, AI study coach, and a deterministic
accounting workbench. Everything runs on your own computer: **no cloud, no
accounts, no telemetry.**

## What it does

| Section | What you get |
|---|---|
| 📊 Dashboard | Recent documents, chats, notes, revision tasks, analysis reports |
| 🎓 Study Coach | Q&A grounded in *your* documents (with citations), simple explanations, AI-generated practice MCQs, answer feedback, weak-topic tracking |
| 📚 Document Library | Import PDF / DOCX / TXT / Markdown / CSV / XLSX, keyword search, previews, duplicate detection, optional OCR for scanned PDFs |
| 🧮 Accounting Workbench | File inspection, duplicate detection, two-way reconciliation, data validation, CSV/XLSX report export — all computed by tested Python code, never by the AI |
| ✅ Revision Tracker | Tasks with due dates, notes, bookmarks |
| ⚙️ Settings & Diagnostics | Ollama model selection, timeouts, OCR toggle, backup/restore, privacy status |

**Design guarantees:** the app works fully when the AI model is unavailable
(search + all workbench tools keep working); document text is treated as
untrusted data, never as instructions; the AI provider must be localhost —
a cloud host is refused.

## Windows setup (exact commands)

Requirements: Windows 10/11, Python 3.10+ from https://www.python.org
(check "Add python.exe to PATH" during install).

**Easy way:** extract the ZIP and double-click **`run_windows.bat`**. It installs
Python itself if missing (via winget), creates a virtual environment, installs
dependencies (internet needed once), and starts the app at
http://127.0.0.1:8501. Truly one double-click.

**Manual way** (Command Prompt):

```bat
cd C:\path\to\ca-copilot
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
streamlit run app.py
```

Then open http://127.0.0.1:8501 in your browser. Close the terminal window to
stop the app.

### Optional: local AI (Ollama)

The app is useful without AI, but Study Coach answers are richer with a model:

1. Install Ollama from https://ollama.com/download/windows
2. `ollama pull qwen3:1.7b` (small, suits 8 GB RAM — ~1 GB download, once)
3. Make sure Ollama is running, then open CA Copilot → Settings shows 🟢 ready.

No model is ever downloaded automatically. Any installed Ollama model can be
selected in Settings.

### Optional: OCR for scanned PDFs

1. Install Tesseract-OCR from https://github.com/UB-Mannheim/tesseract/wiki
2. In CA Copilot → Settings, enable OCR.

Without OCR, scanned/image-only PDFs are **flagged as unread** — the app never
pretends it read them.

## Your data

Everything lives in one folder (nothing in the source tree, nothing in temp):

- **Windows:** `%LOCALAPPDATA%\CA Copilot` (e.g. `C:\Users\Bilal\AppData\Local\CA Copilot`)
- Inside: `app.db` (SQLite), `documents/` (imported copies), `reports/`,
  `backups/`, `config.json`, `logs/`

**Backup:** Settings → "Create backup now" produces a timestamped ZIP in
`backups/`. Or just copy the whole data folder. **Restore:** extract a backup
ZIP into an *empty* folder (the app refuses to merge into live data).

## Running the tests

```bat
run_tests.bat
```
or `pytest tests/ -q` in the activated venv. 40 automated tests cover the
database, document import/search, the workbench (against hand-computed
expectations on fictional sample data in `sample_data/`), study fallback,
revision tracking, backup/restore, and provider safeguards.
See `docs/TEST_REPORT.md`.

## Offline use

After the one-time dependency install (and optional model download), the app
works with **no internet**: Streamlit telemetry is disabled
(`.streamlit/config.toml`), the server binds to 127.0.0.1 only, and every
feature except the Ollama chat needs nothing but localhost.

## Project structure

```
app.py                  Streamlit UI (6 sections)
run_windows.bat         Windows launcher
requirements.txt        Pinned-compatible dependencies
config.example.json     Safe default settings
src/ca_copilot/
    paths.py            data-directory locations
    config.py           settings load/save
    db.py               SQLite + versioned migrations
    migrations/         SQL migration files
    extractors.py       PDF/DOCX/TXT/CSV/XLSX text extraction (+optional OCR)
    documents.py        library: import, FTS5 search, previews
    ai.py               local AI provider interface (Ollama)
    study.py            grounded Q&A, MCQ generation, grading, weak topics
    workbench.py        deterministic inspection/duplicates/reconciliation/validation
    revision.py         subjects, topics, tasks, notes
    backup.py           backup / restore
    tax_rules.py        Pakistan tax framework (safeguards only — no rates shipped)
tests/                  pytest suite (40 tests)
sample_data/            fictional datasets + study doc + question bank
docs/                   test report, privacy & limitations
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `py` not recognized | Reinstall Python with "Add python.exe to PATH" checked |
| Port 8501 in use | `streamlit run app.py --server.port 8502` |
| AI shows "not running" | Start the Ollama app; check Settings → model installed |
| Model slow / out of memory | Use a smaller model (qwen3:1.7b) or close other apps |
| Scanned PDF shows "needs OCR" | Enable OCR in Settings after installing Tesseract |
| Import fails on a file | The file may be corrupt/encrypted — the app reports why instead of crashing |
