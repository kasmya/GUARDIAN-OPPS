"""Tiny SQLite store for incidents and approvals.

Kept intentionally small — a single table, one connection helper. If the
project ever grew we would swap to SQLAlchemy, but right now readability wins.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import DB_PATH, DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    action TEXT,
    reasoning TEXT,
    evidence_json TEXT,
    blast_radius INTEGER DEFAULT 0,
    mttr_seconds REAL,
    report_path TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


def create_incident(
    type_: str,
    status: str,
    reasoning: str,
    evidence: dict,
    action: str | None = None,
) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO incidents (type, status, detected_at, action, reasoning, evidence_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (type_, status, _now(), action, reasoning, json.dumps(evidence)),
        )
        return int(cur.lastrowid)


def resolve_incident(
    incident_id: int,
    action: str,
    mttr_seconds: float,
    blast_radius: int,
    report_path: str | None = None,
) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE incidents SET status='resolved', resolved_at=?, action=?, "
            "mttr_seconds=?, blast_radius=?, report_path=? WHERE id=?",
            (_now(), action, mttr_seconds, blast_radius, report_path, incident_id),
        )


def set_pending_approval(incident_id: int, action_suggested: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE incidents SET status='pending_approval', action=? WHERE id=?",
            (action_suggested, incident_id),
        )


def list_incidents(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row(r) for r in rows]


def list_pending_approvals() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM incidents WHERE status='pending_approval' ORDER BY id DESC"
        ).fetchall()
        return [_row(r) for r in rows]


def get_incident(incident_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return _row(r) if r else None


def latest_resolved() -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM incidents WHERE status='resolved' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row(r) if r else None


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    if d.get("evidence_json"):
        try:
            d["evidence"] = json.loads(d["evidence_json"])
        except json.JSONDecodeError:
            d["evidence"] = {}
    d.pop("evidence_json", None)
    return d
