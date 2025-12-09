"""Public entrypoints for downstream report generators."""

from __future__ import annotations

from typing import List, Dict

from .month_service import ensure_month_events


def _month_key(year: int, month: int) -> str:
    if not (1 <= month <= 12):
        raise ValueError("month must be 1-12")
    return f"{year:04d}-{month:02d}"


def get_events_for_month(year: int, month: int, force_refresh: bool = False, use_llm: bool = True, llm_model: str | None = None) -> List[Dict]:
    key = _month_key(year, month)
    return ensure_month_events(key, "macro", force_refresh=force_refresh, use_llm=use_llm, llm_model=llm_model)


# Legacy wrappers
def get_events_for_nfp_report(year: int, month: int, force_refresh: bool = False, use_llm: bool = False, llm_model: str | None = None) -> List[Dict]:
    return get_events_for_month(year, month, force_refresh=force_refresh, use_llm=use_llm, llm_model=llm_model)


def get_events_for_cpi_report(year: int, month: int, force_refresh: bool = False, use_llm: bool = False, llm_model: str | None = None) -> List[Dict]:
    return get_events_for_month(year, month, force_refresh=force_refresh, use_llm=use_llm, llm_model=llm_model)
