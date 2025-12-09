"""SQLite helpers for macro events storage."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import DATA_DIR, DEFAULT_DB_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: str | Path = DEFAULT_DB_PATH):
    """
    Return a SQLite connection and ensure tables exist.
    """
    db_path = Path(db_path)
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """
    Create months / events / raw_articles tables if missing.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS months (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month_key TEXT NOT NULL,
            report_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'empty',
            num_events INTEGER NOT NULL DEFAULT 0,
            last_refreshed_at TEXT,
            query_version TEXT,
            llm_version TEXT,
            events_payload TEXT,
            monthly_summary TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(month_key, report_type)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month_id INTEGER NOT NULL,
            month_key TEXT NOT NULL,
            report_type TEXT NOT NULL,
            macro_shock_type TEXT NOT NULL,
            impact_channel TEXT NOT NULL,
            date TEXT NOT NULL,
            countries TEXT,
            importance_score REAL NOT NULL DEFAULT 0.0,
            title TEXT,
            summary_zh TEXT,
            summary_en TEXT,
            source_titles TEXT,
            source_urls TEXT,
            source_domains TEXT,
            source_meta TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(month_id) REFERENCES months(id)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT,
            published_at TEXT,
            snippet TEXT,
            full_text TEXT,
            source_domain TEXT,
            first_seen_at TEXT
        );
        """
    )
    # Migration: add monthly_summary column if missing.
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(months)")]
    if "monthly_summary" not in cols:
        conn.execute("ALTER TABLE months ADD COLUMN monthly_summary TEXT;")
    cols_events = [row["name"] for row in conn.execute("PRAGMA table_info(events)")]
    if "source_meta" not in cols_events:
        conn.execute("ALTER TABLE events ADD COLUMN source_meta TEXT;")
    conn.commit()


def get_month_record(conn: sqlite3.Connection, month_key: str, report_type: str) -> Optional[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM months WHERE month_key = ? AND report_type = ?",
        (month_key, report_type),
    )
    return cur.fetchone()


def upsert_month_record(
    conn: sqlite3.Connection,
    month_key: str,
    report_type: str,
    **fields: Any,
) -> int:
    """
    Insert or update a month record; returns the row id.
    """
    now = _now_iso()
    fields = fields.copy()
    fields.setdefault("created_at", now)
    fields["updated_at"] = now
    columns = ["month_key", "report_type"] + list(fields.keys())
    placeholders = ", ".join("?" for _ in columns)
    values = [month_key, report_type] + list(fields.values())
    update_assignments = ", ".join(
        f"{col}=excluded.{col}" for col in fields.keys() if col != "created_at"
    )
    conn.execute(
        f"""
        INSERT INTO months ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(month_key, report_type)
        DO UPDATE SET {update_assignments}, updated_at=excluded.updated_at;
        """,
        values,
    )
    conn.commit()
    row = get_month_record(conn, month_key, report_type)
    return int(row["id"]) if row else -1


def _normalize_json_field(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def insert_events(
    conn: sqlite3.Connection,
    month_id: int,
    month_key: str,
    report_type: str,
    events: Iterable[Dict[str, Any]],
) -> None:
    now = _now_iso()
    to_insert: List[tuple] = []
    for event in events:
        to_insert.append(
            (
                month_id,
                month_key,
                report_type,
                event.get("macro_shock_type", "other"),
                _normalize_json_field(event.get("impact_channel", [])),
                event.get("date"),
                _normalize_json_field(event.get("countries", [])),
                float(event.get("importance_score", 0.0)),
                event.get("title"),
                event.get("summary_zh"),
                event.get("summary_en"),
                _normalize_json_field(event.get("source_titles", [])),
                _normalize_json_field(event.get("source_urls", [])),
                _normalize_json_field(event.get("source_domains", [])),
                _normalize_json_field(event.get("source_meta", [])),
                now,
                now,
            )
        )
    conn.executemany(
        """
        INSERT INTO events (
            month_id, month_key, report_type, macro_shock_type, impact_channel,
            date, countries, importance_score, title, summary_zh, summary_en,
            source_titles, source_urls, source_domains, source_meta, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        to_insert,
    )
    conn.commit()


def get_events_for_month(conn: sqlite3.Connection, month_key: str, report_type: str) -> List[Dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT * FROM events
        WHERE month_key = ? AND report_type = ?
        ORDER BY importance_score DESC, date ASC;
        """,
        (month_key, report_type),
    )
    rows = cur.fetchall()
    events: List[Dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        for key in ("impact_channel", "countries", "source_titles", "source_urls", "source_domains", "source_meta"):
            if event.get(key):
                try:
                    event[key] = json.loads(event[key])
                except json.JSONDecodeError:
                    pass
        events.append(event)
    return events


def upsert_raw_article(conn: sqlite3.Connection, article: Dict[str, Any]) -> None:
    """
    Upsert a raw article based on URL uniqueness.
    """
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO raw_articles (url, title, published_at, snippet, full_text, source_domain, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title=excluded.title,
            published_at=excluded.published_at,
            snippet=excluded.snippet,
            full_text=excluded.full_text,
            source_domain=excluded.source_domain;
        """,
        (
            article.get("url"),
            article.get("title"),
            article.get("published_at"),
            article.get("snippet"),
            article.get("full_text"),
            article.get("source_domain"),
            article.get("first_seen_at", now),
        ),
    )
    conn.commit()
