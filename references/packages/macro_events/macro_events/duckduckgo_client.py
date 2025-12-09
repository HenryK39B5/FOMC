"""DuckDuckGo news search wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional
from urllib.parse import urlparse

try:
    from dateutil import parser as date_parser
except ImportError:  # pragma: no cover - optional dependency
    date_parser = None

try:
    from ddgs import DDGS
except ImportError as exc:  # pragma: no cover - dependency missing
    raise ImportError("Please install ddgs (pip install ddgs)") from exc


@dataclass
class NewsItem:
    title: str
    url: str
    published_at: Optional[date]
    snippet: Optional[str]
    source: Optional[str]
    full_text: Optional[str] = None
    is_primary: bool = False


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    if date_parser is None:
        return None
    try:
        return date_parser.parse(value).date()
    except Exception:
        return None


def _timelimit_for_range(start_date: date, end_date: date) -> Optional[str]:
    """
    DDG timelimit is relative to "now", so using 'm' for historical months would
    filter everything out. For windows far from today, return None to avoid
    over-filtering and rely on Python-side date filtering.
    """
    today = date.today()
    window_distance = abs((today - start_date).days)
    if window_distance > 45 or start_date > today + timedelta(days=45):
        return None
    delta_days = (end_date - start_date).days
    if delta_days <= 7:
        return "w"
    if delta_days <= 31:
        return "m"
    return "y"


def search_news_ddg(query: str, start_date: date, end_date: date, max_results: int = 40) -> List[NewsItem]:
    """
    Use duckduckgo_search / DDGS news API to fetch news results.
    """
    timelimit = _timelimit_for_range(start_date, end_date)
    items: List[NewsItem] = []
    seen_urls = set()

    with DDGS() as ddgs:
        news_kwargs = {
            "query": query,
            "region": "wt-wt",
            "safesearch": "moderate",
            "max_results": max_results,
        }
        if timelimit:
            news_kwargs["timelimit"] = timelimit

        for result in ddgs.news(**news_kwargs):
            url = result.get("url")
            title = result.get("title") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            published_at = _parse_date(result.get("date"))
            snippet = result.get("body") or result.get("snippet")
            source_domain = result.get("source") or urlparse(url).netloc

            # Python-side date filtering to approximate monthly slices.
            if published_at and (published_at < start_date or published_at > end_date):
                continue

            items.append(
                NewsItem(
                    title=title,
                    url=url,
                    published_at=published_at,
                    snippet=snippet,
                    source=source_domain,
                )
            )
            if len(items) >= max_results:
                break
    return items
