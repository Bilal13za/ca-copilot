"""Thread-safety regression tests.

Streamlit executes script reruns on different threads. A database connection
created on one thread must never blow up with sqlite3.ProgrammingError when
the UI (or any caller) touches it from another thread.
"""

import threading

from ca_copilot import db


def test_connection_usable_from_another_thread():
    """Reproduces the crash seen on Windows: connection made on thread A,
    used on thread B."""
    conn = db.get_db()  # created on the main thread
    errors: list[BaseException] = []

    def worker():
        try:
            conn.execute("SELECT COUNT(*) FROM documents").fetchone()
            key = f"thread_test_{threading.get_ident()}"
            with db.transaction(conn) as cur:
                cur.execute(
                    "INSERT INTO settings_kv(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, "ok"))
        except BaseException as exc:  # noqa: BLE001 - we assert on these
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    conn.close()
    assert not errors, f"thread errors: {errors}"


def test_independent_connections_per_thread():
    """The supported pattern: each thread opens and closes its own connection."""
    errors: list[BaseException] = []

    def worker(n: int):
        try:
            c = db.get_db()
            try:
                with db.transaction(c) as cur:
                    cur.execute(
                        "INSERT INTO settings_kv(key, value) VALUES (?, ?)",
                        (f"worker_{n}", "ok"))
            finally:
                c.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"thread errors: {errors}"
