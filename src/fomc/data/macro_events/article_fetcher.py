"""Fetch article bodies and decide which URLs warrant fetching via LLM."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

import requests
from bs4 import BeautifulSoup

from .llm_client import classify_links_importance
from .duckduckgo_client import NewsItem
from .db import upsert_raw_article


def _extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def fetch_articles(urls: Iterable[str], timeout: int = 8) -> Dict[str, str]:
    bodies: Dict[str, str] = {}
    for url in urls:
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            bodies[url] = _extract_text_from_html(resp.text)
        except Exception:
            continue
    return bodies


def decide_urls_for_fetch(news_items: List[NewsItem], max_urls: int = 12, model: str | None = None) -> List[str]:
    if not news_items:
        return []
    try:
        idxs = classify_links_importance([item.__dict__ for item in news_items], max_primary=max_urls, model=model)
    except Exception:
        idxs = []
    if not idxs:
        return [item.url for item in news_items[:max_urls]]
    return [news_items[i].url for i in idxs if 0 <= i < len(news_items)]


def persist_raw_articles(conn, news_items: List[NewsItem], bodies: Dict[str, str]):
    """
    Save raw snippets/full_text for later display.
    """
    for item in news_items:
        upsert_raw_article(
            conn,
            {
                "url": item.url,
                "title": item.title,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "snippet": item.snippet,
                "full_text": bodies.get(item.url),
                "source_domain": item.source,
            },
        )
