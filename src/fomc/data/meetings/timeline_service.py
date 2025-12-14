from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from fomc.data.database.models import EconomicDataPoint, EconomicIndicator
from fomc.data.meetings.calendar_service import FomcMeeting, ensure_fomc_calendar
from fomc.config.paths import MEETING_RUNS_DIR


class Decision(str, Enum):
    HIKE = "HIKE"
    CUT = "CUT"
    HOLD = "HOLD"


class Regime(str, Enum):
    TIGHTENING = "TIGHTENING"
    EASING = "EASING"
    HOLDING = "HOLDING"


DFEDTARL = "DFEDTARL"
DFEDTARU = "DFEDTARU"


def _find_indicator_id(session: Session, code: str) -> Optional[int]:
    row = session.query(EconomicIndicator.id).filter(EconomicIndicator.code == code).first()
    return int(row[0]) if row else None


def _as_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


def _latest_value_on_or_before(session: Session, *, indicator_id: int, on_or_before: datetime) -> Optional[Tuple[datetime, float]]:
    row = (
        session.query(EconomicDataPoint.date, EconomicDataPoint.value)
        .filter(EconomicDataPoint.indicator_id == indicator_id)
        .filter(EconomicDataPoint.date <= on_or_before)
        .order_by(EconomicDataPoint.date.desc())
        .first()
    )
    if not row:
        return None
    dt, val = row
    if val is None:
        return None
    return dt, float(val)


def _latest_value_before(session: Session, *, indicator_id: int, before: datetime) -> Optional[Tuple[datetime, float]]:
    row = (
        session.query(EconomicDataPoint.date, EconomicDataPoint.value)
        .filter(EconomicDataPoint.indicator_id == indicator_id)
        .filter(EconomicDataPoint.date < before)
        .order_by(EconomicDataPoint.date.desc())
        .first()
    )
    if not row:
        return None
    dt, val = row
    if val is None:
        return None
    return dt, float(val)


def _first_value_on_or_after(
    session: Session,
    *,
    indicator_id: int,
    on_or_after: datetime,
    max_days: int = 7,
) -> Optional[Tuple[datetime, float]]:
    upper = on_or_after + timedelta(days=max_days)
    row = (
        session.query(EconomicDataPoint.date, EconomicDataPoint.value)
        .filter(EconomicDataPoint.indicator_id == indicator_id)
        .filter(EconomicDataPoint.date >= on_or_after)
        .filter(EconomicDataPoint.date <= upper)
        .order_by(EconomicDataPoint.date.asc())
        .first()
    )
    if not row:
        return None
    dt, val = row
    if val is None:
        return None
    return dt, float(val)


def _post_value_near_decision(
    session: Session,
    *,
    indicator_id: int,
    decision_dt: datetime,
    pre_value: Optional[float],
    max_days: int = 7,
) -> Optional[Tuple[datetime, float]]:
    """
    Pick a post-decision value robustly.

    Many policy-rate range series reflect the *effective* date, often the day after the decision.
    We therefore scan a short forward window and prefer the first value that differs from pre_value.
    """
    upper = decision_dt + timedelta(days=max_days)
    rows = (
        session.query(EconomicDataPoint.date, EconomicDataPoint.value)
        .filter(EconomicDataPoint.indicator_id == indicator_id)
        .filter(EconomicDataPoint.date >= decision_dt)
        .filter(EconomicDataPoint.date <= upper)
        .order_by(EconomicDataPoint.date.asc())
        .all()
    )
    if not rows:
        return None
    # Prefer first value that differs from pre_value (if we have it).
    if pre_value is not None:
        for dt, val in rows:
            if val is None:
                continue
            if float(val) != float(pre_value):
                return dt, float(val)
    # Otherwise, take the earliest available value in the window.
    dt, val = rows[0]
    if val is None:
        return None
    return dt, float(val)
def _format_range(lower: Optional[float], upper: Optional[float]) -> Optional[str]:
    if lower is None or upper is None:
        return None
    return f"{lower:.2f}–{upper:.2f}"


def _sim_status_for_meeting(meeting_id: str) -> Dict[str, Any]:
    run_dir = MEETING_RUNS_DIR / meeting_id
    manifest = run_dir / "manifest.json"
    if not manifest.exists():
        return {"has_context": False, "has_run": False}
    # we intentionally avoid parsing JSON (keeps endpoint cheap/robust)
    has_artifacts = any(p.suffix == ".md" for p in run_dir.glob("*.md"))
    return {"has_context": True, "has_run": True, "has_artifacts": has_artifacts}


def build_meetings_timeline(
    *,
    session: Session,
    start: date,
    end: date,
    history_cutoff: date,
    refresh_calendar: bool = False,
    k: int = 2,
    m_hold: int = 3,
    delta_threshold_bps: float = 1.0,
) -> Dict[str, Any]:
    """
    Build a meetings timeline with:
    - decision: HIKE/CUT/HOLD based on DFEDTARL/U changes around decision date (meeting end date)
    - regime: TIGHTENING/EASING/HOLDING computed by simple, explainable rules
    """
    meetings: List[FomcMeeting] = ensure_fomc_calendar(start=start, end=end, force_refresh=refresh_calendar)
    meetings = [m for m in meetings if m.end_date >= start and m.end_date <= end]
    meetings = sorted(meetings, key=lambda m: m.end_date)

    lower_id = _find_indicator_id(session, DFEDTARL)
    upper_id = _find_indicator_id(session, DFEDTARU)

    items: List[Dict[str, Any]] = []
    non_hold_actions: List[float] = []  # signed delta_bps for non-hold meetings
    hold_streak = 0
    prev_regime: Regime = Regime.HOLDING

    for meeting in meetings:
        decision_date = meeting.end_date
        decision_dt = _as_dt(decision_date)

        # Rate range series often updates effective on/after decision day.
        # Use: pre = last before decision_dt; post = first changed value near decision_dt (within a short window).
        pre_lower = _latest_value_before(session, indicator_id=lower_id, before=decision_dt) if lower_id else None
        pre_upper = _latest_value_before(session, indicator_id=upper_id, before=decision_dt) if upper_id else None
        post_lower = (
            _post_value_near_decision(session, indicator_id=lower_id, decision_dt=decision_dt, pre_value=pre_lower[1] if pre_lower else None)
            if lower_id
            else None
        )
        post_upper = (
            _post_value_near_decision(session, indicator_id=upper_id, decision_dt=decision_dt, pre_value=pre_upper[1] if pre_upper else None)
            if upper_id
            else None
        )

        # Fallback if data is sparse for a window
        if lower_id and not post_lower:
            post_lower = _latest_value_on_or_before(session, indicator_id=lower_id, on_or_before=decision_dt + timedelta(days=7))
        if upper_id and not post_upper:
            post_upper = _latest_value_on_or_before(session, indicator_id=upper_id, on_or_before=decision_dt + timedelta(days=7))

        pre_mid = None
        post_mid = None
        if pre_lower and pre_upper:
            pre_mid = (pre_lower[1] + pre_upper[1]) / 2.0
        if post_lower and post_upper:
            post_mid = (post_lower[1] + post_upper[1]) / 2.0

        delta_bps = 0.0
        if pre_mid is not None and post_mid is not None:
            delta_bps = (post_mid - pre_mid) * 100.0

        if delta_bps > delta_threshold_bps:
            decision = Decision.HIKE
            non_hold_actions.append(delta_bps)
            hold_streak = 0
        elif delta_bps < -delta_threshold_bps:
            decision = Decision.CUT
            non_hold_actions.append(delta_bps)
            hold_streak = 0
        else:
            decision = Decision.HOLD
            hold_streak += 1

        # Regime rule: based on last K non-hold actions.
        # - For non-hold meetings: compute from last K actions (including this one).
        # - For hold meetings: inherit previous regime, but decay to HOLDING after M consecutive holds.
        if decision == Decision.HOLD:
            regime = prev_regime
            if hold_streak >= m_hold:
                regime = Regime.HOLDING
        else:
            recent = non_hold_actions[-k:]
            if len(recent) < k:
                regime = Regime.HOLDING
            else:
                if all(x > delta_threshold_bps for x in recent):
                    regime = Regime.TIGHTENING
                elif all(x < -delta_threshold_bps for x in recent):
                    regime = Regime.EASING
                else:
                    regime = Regime.HOLDING

        prev_regime = regime

        is_historical = decision_date <= history_cutoff
        items.append(
            {
                "meeting_id": meeting.meeting_id,
                "meeting_start": meeting.start_date.isoformat(),
                "decision_date": decision_date.isoformat(),
                "title": meeting.label,
                "historical": is_historical,
                "decision": decision.value,
                "delta_bps": round(delta_bps, 1),
                "pre_lower": pre_lower[1] if pre_lower else None,
                "pre_upper": pre_upper[1] if pre_upper else None,
                "target_lower": post_lower[1] if post_lower else None,
                "target_upper": post_upper[1] if post_upper else None,
                "target_range": _format_range(post_lower[1] if post_lower else None, post_upper[1] if post_upper else None),
                "regime": regime.value,
                "sim": _sim_status_for_meeting(meeting.meeting_id),
            }
        )

    # Compute segments for background bands.
    segments: List[Dict[str, Any]] = []
    if items:
        seg_start = items[0]["meeting_id"]
        seg_regime = items[0]["regime"]
        last_id = items[0]["meeting_id"]
        for it in items[1:]:
            if it["regime"] != seg_regime:
                segments.append({"start_meeting_id": seg_start, "end_meeting_id": last_id, "regime": seg_regime})
                seg_start = it["meeting_id"]
                seg_regime = it["regime"]
            last_id = it["meeting_id"]
        segments.append({"start_meeting_id": seg_start, "end_meeting_id": last_id, "regime": seg_regime})

    return {
        "meta": {"start": start.isoformat(), "end": end.isoformat(), "count": len(items)},
        "items": items,
        "regime_segments": segments,
        "params": {"k": k, "m_hold": m_hold, "delta_threshold_bps": delta_threshold_bps},
        "sources": {"calendar": "federalreserve.gov", "target_range": [DFEDTARL, DFEDTARU]},
    }
