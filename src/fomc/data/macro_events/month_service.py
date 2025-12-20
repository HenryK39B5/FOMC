"""Monthly aggregation workflow for macro events."""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Dict, List

from .config import UNIFIED_QUERIES, LLM_VERSION, QUERY_VERSION, REPORT_TYPES
from .db import (
    get_connection,
    get_events_for_month,
    get_month_record,
    insert_events,
    upsert_month_record,
)
from .duckduckgo_client import NewsItem, search_news_ddg
from .event_processing import cluster_candidates, filter_and_classify_news, select_top_events, enrich_events_with_llm
from . import DEFAULT_DB_PATH
from .llm_client import generate_monthly_report, extract_event_keywords
from .article_fetcher import decide_urls_for_fetch, fetch_articles, persist_raw_articles


def _parse_month_key(month_key: str) -> tuple[date, date]:
    try:
        year, month = month_key.split("-")
        year_i, month_i = int(year), int(month)
        if month_i < 1 or month_i > 12:
            raise ValueError
        start_date = date(year_i, month_i, 1)
        end_day = monthrange(year_i, month_i)[1]
        end_date = date(year_i, month_i, end_day)
    except Exception as exc:
        raise ValueError(f"Invalid month_key format: {month_key}") from exc
    return start_date, end_date


def _load_events_payload(payload: str | None) -> List[Dict]:
    if not payload:
        return []
    try:
        data = json.loads(payload)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        return []
    return []


def _search_queries(queries: List[str], start_date: date, end_date: date, max_results: int = 80) -> List[NewsItem]:
    all_news: List[NewsItem] = []
    seen_urls = set()
    for query in queries:
        try:
            results = search_news_ddg(query, start_date, end_date, max_results=max_results)
        except Exception as exc:
            import sys

            print(f"[warn] DDG search failed for query: {query} ({exc})", file=sys.stderr)
            results = []
        print(f"[info] DDG query='{query}' returned {len(results)} results")
        for item in results:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            all_news.append(item)
    return all_news


def _normalize_keyword_query(keyword: str) -> Optional[str]:
    keyword = keyword.strip()
    if not keyword:
        return None
    if not any("a" <= ch.lower() <= "z" for ch in keyword):
        return None
    if " " in keyword and not (keyword.startswith('"') and keyword.endswith('"')):
        return f'"{keyword}"'
    return keyword


def ensure_month_events(
    month_key: str,
    report_type: str | None = None,
    force_refresh: bool = False,
    use_llm: bool = True,
    llm_model: str | None = None,
    db_path=DEFAULT_DB_PATH,
    generate_monthly_summary: bool = True,
    max_events: int = 20,
    fetch_bodies: bool = True,
) -> List[Dict]:
    """
    Ensure events exist for a month/report_type. Fetch from DB or populate via search.
    """
    report_type = report_type or "macro"
    if report_type not in REPORT_TYPES:
        report_type = "macro"

    start_date, end_date = _parse_month_key(month_key)
    conn = get_connection(db_path)
    try:
        record = get_month_record(conn, month_key, report_type)
        if record and record["status"] == "completed" and not force_refresh:
            payload_events = _load_events_payload(record["events_payload"])
            events_from_db = payload_events or get_events_for_month(conn, month_key, report_type)
            # Avoid re-calling LLM on cached months unless explicitly requested and summaries are missing.
            if use_llm and any(not (e.get("summary_zh") or e.get("summary_en")) for e in events_from_db):
                events_from_db = enrich_events_with_llm(events_from_db, report_type, use_llm=True, model=llm_model)
            return events_from_db

        month_id = upsert_month_record(
            conn,
            month_key,
            report_type,
            status="in_progress",
            query_version=QUERY_VERSION,
            llm_version=LLM_VERSION,
        )

        queries = UNIFIED_QUERIES
        all_news = _search_queries(queries, start_date, end_date, max_results=80)

        if use_llm and all_news:
            stage1_candidates = filter_and_classify_news(all_news, report_type, start_date=start_date, end_date=end_date)
            stage1_clustered = cluster_candidates(stage1_candidates, use_llm=use_llm)
            stage1_selected = select_top_events(stage1_clustered, max_events=max_events)
            keywords = extract_event_keywords(stage1_selected, report_type=report_type, model=llm_model)
            keyword_queries: List[str] = []
            seen_keywords = set()
            for keyword in keywords:
                normalized = _normalize_keyword_query(keyword)
                if not normalized or normalized.lower() in seen_keywords:
                    continue
                seen_keywords.add(normalized.lower())
                keyword_queries.append(normalized)
            if keyword_queries:
                stage2_news = _search_queries(keyword_queries, start_date, end_date, max_results=60)
                existing_urls = {item.url for item in all_news}
                for item in stage2_news:
                    if item.url in existing_urls:
                        continue
                    existing_urls.add(item.url)
                    all_news.append(item)

        if fetch_bodies and all_news:
            urls_to_fetch = decide_urls_for_fetch(all_news, max_urls=12, model=llm_model)
            bodies = fetch_articles(urls_to_fetch)
            for item in all_news:
                if item.url in bodies:
                    item.full_text = bodies[item.url]
                item.is_primary = item.url in urls_to_fetch
            # persist raw articles (snippet/full_text) for UI display
            persist_raw_articles(conn, all_news, bodies)
        else:
            for item in all_news:
                item.is_primary = False

        candidates = filter_and_classify_news(all_news, report_type, start_date=start_date, end_date=end_date)
        clustered = cluster_candidates(candidates, use_llm=use_llm)
        selected_events = select_top_events(clustered, max_events=max_events)
        selected_events = enrich_events_with_llm(selected_events, report_type, use_llm=use_llm, model=llm_model)
        if len(selected_events) > max_events:
            selected_events = selected_events[:max_events]

        # Refresh events table for this month/report_type before inserting.
        conn.execute("DELETE FROM events WHERE month_id = ?", (month_id,))
        if selected_events:
            insert_events(conn, month_id, month_key, report_type, selected_events)

        monthly_summary = None
        if generate_monthly_summary and use_llm and selected_events:
            monthly_summary = generate_monthly_report(selected_events, model=llm_model, report_month=month_key)

        now_iso = datetime.now(timezone.utc).isoformat()
        upsert_month_record(
            conn,
            month_key,
            report_type,
            status="completed",
            num_events=len(selected_events),
            last_refreshed_at=now_iso,
            query_version=QUERY_VERSION,
            llm_version=LLM_VERSION,
            events_payload=json.dumps(selected_events, ensure_ascii=False),
            monthly_summary=monthly_summary,
        )
        return selected_events
    except Exception:
        upsert_month_record(
            conn,
            month_key,
            report_type,
            status="failed",
        )
        raise
    finally:
        conn.close()
