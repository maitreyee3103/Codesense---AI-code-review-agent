import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "codesense.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_url      TEXT NOT NULL,
                pr_title    TEXT,
                repo        TEXT,
                pr_number   INTEGER,
                alignment   INTEGER,
                risk        TEXT,
                findings    TEXT,
                reviewed_at TEXT NOT NULL
            )
        """)


def save_review(
    pr_url: str,
    pr_title: str,
    repo: str,
    pr_number: int,
    alignment: int,
    risk: str,
    findings: list,
) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reviews
                (pr_url, pr_title, repo, pr_number, alignment, risk, findings, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pr_url,
                pr_title,
                repo,
                pr_number,
                alignment,
                risk,
                json.dumps(findings),
                datetime.utcnow().isoformat(),
            ),
        )
        return cursor.lastrowid


def get_recent_reviews(limit: int = 10) -> list:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reviews ORDER BY reviewed_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
