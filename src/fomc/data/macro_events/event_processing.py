"""Convert raw news search results into structured macro events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from .config import IMPACT_CHANNELS, MACRO_SHOCK_TYPES
from .duckduckgo_client import NewsItem


@dataclass
class MacroEventCandidate:
    date: str  # "YYYY-MM-DD"
    macro_shock_type: str
    impact_channel: List[str]
    countries: List[str]
    summary_zh: str
    source_title: str
    source_url: str
    source_domain: str
    is_primary: bool


def _classify_text(text: str, report_type: str) -> tuple[str, List[str]]:
    text_lower = text.lower()
    if any(keyword in text_lower for keyword in ["tariff", "trade war", "export control", "sanction"]):
        shock = "trade_tariff" if "tariff" in text_lower or "trade war" in text_lower else "sanctions"
    elif any(keyword in text_lower for keyword in ["port", "shipping", "supply chain", "logistics", "shipment", "canal"]):
        shock = "supply_chain"
    elif any(keyword in text_lower for keyword in ["strike", "walkout", "labor dispute", "uaw", "union"]):
        shock = "labor_dispute"
    elif any(keyword in text_lower for keyword in ["bank failure", "bank collapse", "liquidity", "bank run", "credit crunch"]):
        shock = "financial_stability"
    else:
        shock = "other"

    impact: List[str] = []
    if "inflation" in text_lower or "price" in text_lower or report_type == "cpi":
        impact.append("inflation")
    if "job" in text_lower or "employment" in text_lower or report_type == "nfp":
        impact.append("employment")
    if any(keyword in text_lower for keyword in ["gdp", "growth", "output", "factory"]):
        impact.append("growth")
    if any(keyword in text_lower for keyword in ["credit", "liquidity", "bank", "yields", "bonds"]):
        impact.append("financial_conditions")
    if not impact:
        impact.append("growth")
    # keep ordering and deduplicate
    seen = set()
    impact_dedup: List[str] = []
    for channel in impact:
        if channel in seen:
            continue
        if channel in IMPACT_CHANNELS:
            impact_dedup.append(channel)
            seen.add(channel)
    return shock, impact_dedup


def _infer_countries(text: str) -> List[str]:
    text_lower = text.lower()
    countries: List[str] = []
    if any(keyword in text_lower for keyword in ["united states", "u.s.", "usa", "us "]):
        countries.append("US")
    if "china" in text_lower or "chinese" in text_lower or "prc" in text_lower:
        countries.append("CN")
    if "europe" in text_lower or "euro" in text_lower:
        countries.append("EU")
    if not countries:
        countries.append("US")
    return countries


def filter_and_classify_news(
    news_list: List[NewsItem],
    report_type: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> List[MacroEventCandidate]:
    """
    Filter NewsItem list and attach coarse labels for later clustering.
    """
    seen_urls = set()
    candidates: List[MacroEventCandidate] = []
    for item in news_list:
        if item.url in seen_urls:
            continue
        seen_urls.add(item.url)

        if start_date and end_date and item.published_at:
            if not (start_date <= item.published_at <= end_date):
                continue

        # For important links prefer full_text; otherwise use snippet/body.
        snippet_or_body = item.full_text if getattr(item, "is_primary", False) and item.full_text else (item.snippet or "")
        text_blob = " ".join(filter(None, [item.title, snippet_or_body])).strip()
        if not text_blob:
            continue

        macro_shock_type, impact_channel = _classify_text(text_blob, report_type)
        countries = _infer_countries(text_blob)

        # Store raw content for downstream clustering/summarization:
        # primary -> use full_text (truncated), supplementary -> use snippet/body
        content_for_summary = snippet_or_body if snippet_or_body else item.title
        if content_for_summary and len(content_for_summary) > 500:
            content_for_summary = content_for_summary[:500] + "..."
        summary_zh = f"{item.source or '来源未知'}：{content_for_summary}"
        candidates.append(
            MacroEventCandidate(
                date=item.published_at.isoformat() if item.published_at else "",
                macro_shock_type=macro_shock_type,
                impact_channel=impact_channel,
                countries=countries,
                summary_zh=summary_zh,
                source_title=item.title,
                source_url=item.url,
                source_domain=item.source or "",
                is_primary=getattr(item, "is_primary", False),
            )
        )
    return candidates


def cluster_candidates(candidates: List[MacroEventCandidate]) -> List[Dict]:
    """
    Merge similar candidates into macro events.
    Currently groups by (date, macro_shock_type) and aggregates sources.
    """
    clusters: Dict[tuple, Dict] = {}
    for cand in candidates:
        key = (cand.date, cand.macro_shock_type)
        if key not in clusters:
            clusters[key] = {
                "date": cand.date,
                "macro_shock_type": cand.macro_shock_type,
                "impact_channel": set(cand.impact_channel),
                "countries": set(cand.countries),
                "summaries": [cand.summary_zh],
                "source_meta": [
                    {
                        "title": cand.source_title,
                        "url": cand.source_url,
                        "domain": cand.source_domain,
                        "important": cand.is_primary,
                    }
                ],
            }
        else:
            cluster = clusters[key]
            cluster["impact_channel"].update(cand.impact_channel)
            cluster["countries"].update(cand.countries)
            cluster["summaries"].append(cand.summary_zh)
            cluster["source_meta"].append(
                {
                    "title": cand.source_title,
                    "url": cand.source_url,
                    "domain": cand.source_domain,
                    "important": cand.is_primary,
                }
            )

    high_quality_domains = {"wsj.com", "ft.com", "reuters.com", "bloomberg.com"}
    merged: List[Dict] = []
    for cluster in clusters.values():
        domains_all = [s.get("domain") for s in cluster["source_meta"] if s.get("domain")]
        domain_bonus = sum(1 for d in domains_all if d in high_quality_domains)
        importance_score = len(cluster["source_meta"]) + 0.5 * domain_bonus
        primary_meta = [s for s in cluster["source_meta"] if s.get("important")]
        supp_meta = [s for s in cluster["source_meta"] if not s.get("important")]
        source_titles = [s.get("title") for s in cluster["source_meta"]]
        source_urls = [s.get("url") for s in cluster["source_meta"]]
        source_domains = domains_all
        merged.append(
            {
                "date": cluster["date"],
                "macro_shock_type": cluster["macro_shock_type"],
                "impact_channel": sorted(cluster["impact_channel"]),
                "countries": sorted(cluster["countries"]),
                "importance_score": importance_score,
                "title": source_titles[0] if source_titles else "",
                "summary_zh": "；".join(cluster["summaries"]),
                "summary_en": None,
                "source_titles": source_titles,
                "source_urls": source_urls,
                "source_domains": source_domains,
                "source_meta": cluster["source_meta"],
                "primary_urls": [s.get("url") for s in primary_meta if s.get("url")],
                "supplementary_urls": [s.get("url") for s in supp_meta if s.get("url")],
            }
        )
    return merged


def select_top_events(clustered_events: List[Dict], max_events: int = 10) -> List[Dict]:
    """
    Sort events by importance and return the top N (adaptive: score threshold + cap).
    """
    sorted_events = sorted(
        clustered_events,
        key=lambda e: (-e.get("importance_score", 0), e.get("date") or ""),
    )
    if not sorted_events:
        return []
    scores = [e.get("importance_score", 0) for e in sorted_events]
    # Simple adaptive rule: keep those above max(1.0, 75th percentile) but at least 5, at most max_events.
    scores_sorted = sorted(scores)
    pct75 = scores_sorted[int(0.75 * (len(scores_sorted) - 1))]
    threshold = max(1.0, pct75)
    kept = [e for e in sorted_events if e.get("importance_score", 0) >= threshold]
    if len(kept) < 5:
        kept = sorted_events[:5]
    return kept[:max_events]


def enrich_events_with_llm(events: List[Dict], report_type: str, use_llm: bool = True, model: Optional[str] = None) -> List[Dict]:
    """
    Call LLM to improve summary_zh and reorder by importance.
    """
    if not events:
        return events
    if not use_llm:
        return events
    try:
        from .llm_client import summarize_events_with_llm, llm_rank_and_filter
    except Exception:
        return events
    try:
        enriched = summarize_events_with_llm(events, report_type=report_type, model=model)
        ranked = llm_rank_and_filter(enriched, model=model)
        return ranked
    except Exception:
        return events
