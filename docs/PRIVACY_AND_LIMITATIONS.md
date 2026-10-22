# Privacy & Limitations — CA Copilot Local

## Privacy statement

- **100% local.** The app runs on your computer only. There is no user
  account, no cloud sync, no telemetry, no analytics, and no automatic
  uploads of any kind.
- **Localhost only.** The web interface binds to `127.0.0.1` — it cannot be
  reached from your local network or the internet.
- **Local AI only.** The AI provider interface refuses any host that is not
  loopback (`127.0.0.1`/`localhost`). A cloud model can never be silently
  substituted. No model is downloaded automatically.
- **Your data directory** (`%LOCALAPPDATA%\CA Copilot` on Windows) holds your
  documents, chats, notes, tasks, and reports. Backups are ZIP files stored
  next to your data — never sent anywhere.
- **Document text is untrusted data.** Imported documents are never treated as
  instructions to the AI and cannot override the app's safety rules.
- **No secrets in source code.** There are no API keys or passwords anywhere
  in the project.

## ⚠️ Important limitations

1. **Not approved for client data.** This app is for personal study and
   practice. Firm authorization and appropriate confidentiality controls are
   required before using any real client information.
2. **Study answers are drafts.** AI answers are grounded in your selected
   documents with citations, but the model can misread them. Always verify
   against the source before relying on an answer for exams or work.
3. **Workbench outputs are drafts for human review**, not final professional
   conclusions. Ambiguous matches are flagged, never silently merged — a
   human must resolve them.
4. **No tax computation.** The first release ships no tax rates and performs
   no tax calculations. A future tax module must cite versioned sources with
   tax year and effective date, show workings, and require human review.
5. **Generated practice questions are not official ICAP material** and are
   labelled as such.
6. **Scanned PDFs** are reported as unread unless you explicitly enable OCR
   (requires separate Tesseract-OCR install).
7. **Keyword search, not semantic search.** Use the document's own wording.
8. **Small models are limited.** qwen3:1.7b explains concepts well but is
   weak at long multi-step arithmetic — use the Workbench for calculations.

## Data handling summary

| Data | Where it lives | Leaves the PC? |
|---|---|---|
| Imported documents | `%LOCALAPPDATA%\CA Copilot\documents\` | Never |
| Extracted text index | `app.db` (SQLite FTS5) | Never |
| Chats, notes, tasks | `app.db` | Never |
| Analysis reports | `reports\` + `app.db` | Never (you may export/share files yourself) |
| Backups | `backups\` ZIP files | Never |
| AI prompts | Sent to `http://127.0.0.1:11434` only | Never |
