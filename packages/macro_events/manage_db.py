"""Command-line utilities for managing the macro events SQLite database."""

from __future__ import annotations

import argparse
import json
from typing import Any

from macro_events import DEFAULT_DB_PATH
from macro_events.db import (
    get_connection,
    get_events_for_month,
    get_month_record,
    init_db,
    upsert_month_record,
)
from macro_events.month_service import ensure_month_events


def cmd_init(args: argparse.Namespace) -> None:
    conn = get_connection(args.db_path)
    init_db(conn)
    conn.close()
    print(f"Initialized database at {args.db_path}")


def cmd_list_months(args: argparse.Namespace) -> None:
    conn = get_connection(args.db_path)
    cur = conn.execute("SELECT * FROM months ORDER BY month_key DESC, report_type ASC;")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("No months cached.")
        return
    for row in rows:
        print(
            f"{row['month_key']} / {row['report_type']}: status={row['status']}, "
            f"num_events={row['num_events']}, refreshed={row['last_refreshed_at']}"
        )


def cmd_list_events(args: argparse.Namespace) -> None:
    conn = get_connection(args.db_path)
    events = get_events_for_month(conn, args.month_key, args.report_type)
    conn.close()
    if not events:
        print("No events stored for this month/report_type.")
        return
    for idx, ev in enumerate(events, start=1):
        print(f"[{idx}] {ev.get('date')} {ev.get('macro_shock_type')} score={ev.get('importance_score')}")
        print(f"    summary: {ev.get('summary_zh')}")
        urls = ev.get("source_urls") or []
        domains = ev.get("source_domains") or []
        for u, d in zip(urls, domains):
            print(f"    src: {d} - {u}")


def cmd_refresh_month(args: argparse.Namespace) -> None:
    events = ensure_month_events(
        args.month_key,
        args.report_type,
        force_refresh=args.force,
        llm_model=args.llm_model,
        db_path=args.db_path,
    )
    print(f"Fetched {len(events)} events for {args.month_key} / {args.report_type}")


def cmd_delete_month(args: argparse.Namespace) -> None:
    conn = get_connection(args.db_path)
    conn.execute("DELETE FROM events WHERE month_key = ? AND report_type = ?", (args.month_key, args.report_type))
    conn.execute("DELETE FROM months WHERE month_key = ? AND report_type = ?", (args.month_key, args.report_type))
    conn.commit()
    conn.close()
    print(f"Deleted {args.month_key} / {args.report_type} from database.")


def cmd_reset_status(args: argparse.Namespace) -> None:
    conn = get_connection(args.db_path)
    record = get_month_record(conn, args.month_key, args.report_type)
    if not record:
        print("No record exists; inserting empty placeholder.")
    upsert_month_record(
        conn,
        args.month_key,
        args.report_type,
        status="empty",
        num_events=0,
        events_payload=None,
        last_refreshed_at=None,
    )
    conn.close()
    print(f"Reset status to empty for {args.month_key} / {args.report_type}.")


def cmd_export_month(args: argparse.Namespace) -> None:
    conn = get_connection(args.db_path)
    events = get_events_for_month(conn, args.month_key, args.report_type)
    conn.close()
    print(json.dumps(events, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage macro events database.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Path to SQLite DB (default: data/macro_events.db)")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Create DB and tables if missing")
    p_init.set_defaults(func=cmd_init)

    p_list = sub.add_parser("list-months", help="List cached months and statuses")
    p_list.set_defaults(func=cmd_list_months)

    p_events = sub.add_parser("list-events", help="List events for a month/report_type")
    p_events.add_argument("--month-key", required=True, help="YYYY-MM")
    p_events.add_argument("--report-type", default="macro")
    p_events.set_defaults(func=cmd_list_events)

    p_refresh = sub.add_parser("refresh-month", help="Fetch/refresh events for a month (report_type optional; default macro)")
    p_refresh.add_argument("--month-key", required=True, help="YYYY-MM")
    p_refresh.add_argument("--report-type", default="macro")
    p_refresh.add_argument("--force", action="store_true", help="Force refresh even if completed")
    p_refresh.add_argument("--llm-model", help="Override LLM model name")
    p_refresh.set_defaults(func=cmd_refresh_month)

    p_delete = sub.add_parser("delete-month", help="Delete a month and its events")
    p_delete.add_argument("--month-key", required=True)
    p_delete.add_argument("--report-type", default="macro")
    p_delete.set_defaults(func=cmd_delete_month)

    p_clear = sub.add_parser("clear-all", help="Delete all months/events data")
    p_clear.set_defaults(func=lambda args: clear_all(args.db_path))

    p_reset = sub.add_parser("reset-status", help="Reset month status to empty (keeps/deletes events)")
    p_reset.add_argument("--month-key", required=True)
    p_reset.add_argument("--report-type", default="macro")
    p_reset.set_defaults(func=cmd_reset_status)

    p_export = sub.add_parser("export-month", help="Print events JSON for a month/report_type")
    p_export.add_argument("--month-key", required=True)
    p_export.add_argument("--report-type", default="macro")
    p_export.set_defaults(func=cmd_export_month)

    return parser


def clear_all(db_path: str):
    conn = get_connection(db_path)
    conn.execute("DELETE FROM events;")
    conn.execute("DELETE FROM months;")
    conn.commit()
    conn.close()
    print("Cleared all months and events.")


def main(argv: Any = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
