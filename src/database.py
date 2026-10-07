"""SQLite persistence for deduplication.

Stores UIDs of jobs that have been successfully processed and emailed so they
are never sent twice. All queries are parameterized.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from src.models import Job

DEFAULT_DB_PATH = os.path.join("database", "jobs.db")


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    return sqlite3.connect(db_path)


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_jobs (
                uid        TEXT PRIMARY KEY,
                title      TEXT,
                company    TEXT,
                url        TEXT,
                source     TEXT,
                first_seen TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def is_seen(uid: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute("SELECT 1 FROM seen_jobs WHERE uid = ?", (uid,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def mark_seen(job: Job, db_path: str = DEFAULT_DB_PATH) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO seen_jobs (uid, title, company, url, source, first_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job.uid,
                job.title,
                job.company,
                job.url,
                job.source,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def count_seen(db_path: str = DEFAULT_DB_PATH) -> int:
    conn = _connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM seen_jobs")
        return int(cur.fetchone()[0])
    finally:
        conn.close()
