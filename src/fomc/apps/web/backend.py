"""
Integration layer that stitches together the existing report generator (Flask)
and the macro-events pipeline so the portal can expose them behind one API.
"""

from __future__ import annotations

from typing import Any, Dict

import markdown2

from fomc.config import MACRO_EVENTS_DB_PATH, load_env
from fomc.apps.flaskapp.app import app as reports_app  # type: ignore
from fomc.data.macro_events.db import get_connection, get_month_record
from fomc.data.macro_events.month_service import ensure_month_events

load_env()


class PortalError(RuntimeError):
    """Raised when an underlying app returns a failure."""


def _call_flask_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke an existing Flask endpoint inside the same process."""
    with reports_app.test_client() as client:
        resp = client.post(path, json=payload)
        if resp.status_code >= 400:
            try:
                detail = resp.get_json() or {}
            except Exception:
                detail = {}
            message = detail.get("error") or resp.data.decode("utf-8") or f"HTTP {resp.status_code}"
            raise PortalError(message)
        return resp.get_json()  # type: ignore[return-value]


def generate_labor_report(month: str) -> Dict[str, Any]:
    """Generate labor-market report payload via the existing Flask app."""
    return _call_flask_json("/api/labor-market/report", {"report_month": month})


def generate_cpi_report(month: str) -> Dict[str, Any]:
    """Generate CPI report payload via the existing Flask app."""
    return _call_flask_json("/api/cpi/report", {"report_month": month})


def get_macro_month(month_key: str, refresh: bool = False) -> Dict[str, Any]:
    """
    Fetch macro events for a month, optionally forcing refresh via DDG+LLM.
    Returns events plus the stored monthly summary (HTML for UI).
    """
    events = ensure_month_events(month_key, db_path=MACRO_EVENTS_DB_PATH, force_refresh=refresh)

    conn = get_connection(MACRO_EVENTS_DB_PATH)
    try:
        record = get_month_record(conn, month_key, "macro")
        summary_md = record["monthly_summary"] if record else None
        summary_html = markdown2.markdown(summary_md) if summary_md else None
        payload = {
            "month_key": month_key,
            "status": record["status"] if record else "unknown",
            "last_refreshed_at": record["last_refreshed_at"] if record else None,
            "num_events": record["num_events"] if record else len(events),
            "events": [_shape_event(e) for e in events],
            "monthly_summary_md": summary_md,
            "monthly_summary_html": summary_html,
        }
        return payload
    finally:
        conn.close()


def _shape_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw DB row for the UI."""
    return {
        "date": event.get("date"),
        "title": event.get("title"),
        "summary": event.get("summary_zh") or event.get("summary_en"),
        "macro_shock_type": event.get("macro_shock_type"),
        "impact_channel": event.get("impact_channel"),
        "importance_score": event.get("importance_score"),
        "sources": event.get("source_titles") or [],
        "source_urls": event.get("source_urls") or [],
    }
