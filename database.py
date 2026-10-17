"""SQLite storage for alert history (surveillance.db in the project folder)."""

import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone

from config import Config

DB_PATH = Config.BASE_DIR / "surveillance.db"

# GUI thread aur capture thread ek saath likhein to takraav na ho.
_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the table if it does not exist. Safe to call on every start."""
    with _lock, closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TEXT    NOT NULL,
                class_name  TEXT    NOT NULL,
                confidence  REAL    NOT NULL,
                model       TEXT,
                track_id    INTEGER,
                source      TEXT,
                image_path  TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts(detected_at)")


def save_alert(class_name, confidence, model=None, track_id=None, source=None, image_path=None):
    """Insert one alert row and return its id."""
    with _lock, closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO alerts (detected_at, class_name, confidence, model, track_id, source, image_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                str(class_name),
                float(confidence),
                model,
                track_id,
                source,
                image_path,
            ),
        )
        return cur.lastrowid


def recent_alerts(limit=50):
    """Newest alerts first, as a list of dicts."""
    with _lock, closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (int(limit),))
        return [dict(row) for row in rows]


def counts_by_class():
    """[{'class_name': ..., 'total': ...}, ...] most frequent first."""
    with _lock, closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT class_name, COUNT(*) AS total FROM alerts GROUP BY class_name ORDER BY total DESC"
        )
        return [dict(row) for row in rows]