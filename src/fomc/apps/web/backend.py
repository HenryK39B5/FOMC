"""
Integration layer that stitches together the existing report generator (Flask)
and the macro-events pipeline so the portal can expose them behind one API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import io
import threading
import time
from typing import Any, Dict, List, Optional
import uuid
import html
import re
import base64

import markdown2

from fomc.config import MACRO_EVENTS_DB_PATH, load_env
from fomc.apps.flaskapp.app import app as reports_app  # type: ignore
from fomc.config import MAIN_DB_PATH, REPO_ROOT
from fomc.data.database.connection import SessionLocal
from fomc.data.database.models import EconomicDataPoint, EconomicIndicator, IndicatorCategory
from fomc.data.macro_events.db import get_connection, get_month_record, get_events_for_month
from fomc.data.macro_events.month_service import ensure_month_events
from fomc.data.indicators.indicator_sync_pipeline import IndicatorSyncPipeline
from fomc.data.indicators.data_updater import IndicatorDataUpdater
from fomc.data.meetings.calendar_service import ensure_fomc_calendar
from fomc.data.meetings.run_store import (
    ensure_meeting_run,
    load_manifest,
    set_context,
    read_artifact_text,
    read_artifact_json,
    write_artifact_text,
    write_artifact_json,
)
from fomc.infra.llm import LLMClient
from fomc.data.meetings.discussion_service import (
    DEFAULT_ROLES,
    build_blackboard,
    infer_crisis_mode,
    generate_stance_card,
    generate_public_speech,
    chair_select_questions,
    chair_propose_packages,
    generate_package_preference,
    generate_vote,
    secretary_round_summary,
    chair_write_statement_and_minutes,
    render_discussion_markdown,
)
from fomc.rules.taylor_rule import ModelType
from fomc.data.modeling.taylor_service import build_taylor_series_from_db
from datetime import timedelta
from fomc.data.meetings.timeline_service import build_meetings_timeline

load_env()


class PortalError(RuntimeError):
    """Raised when an underlying app returns a failure."""


DEFAULT_MEETING_RANGE_START = date(2010, 1, 1)
DEFAULT_MEETING_RANGE_END = date(2027, 12, 31)
DEFAULT_HISTORY_CUTOFF = date(2025, 12, 31)


def _month_key(dt: date) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _add_months(dt: date, delta_months: int) -> date:
    y = dt.year + (dt.month - 1 + delta_months) // 12
    m = (dt.month - 1 + delta_months) % 12 + 1
    return date(y, m, 1)


def _month_key_offset(month_key: str, delta_months: int) -> str:
    y, m = (int(x) for x in month_key.split("-", 1))
    base = date(y, m, 1)
    shifted = _add_months(base, delta_months)
    return _month_key(shifted)


def _compute_meeting_report_months(current_end: date, previous_end: Optional[date]) -> list[str]:
    focus = _month_key(_add_months(date(current_end.year, current_end.month, 1), -1))
    months = [focus]
    if not previous_end:
        return months

    cur_idx = current_end.year * 12 + current_end.month
    prev_idx = previous_end.year * 12 + previous_end.month
    gap = cur_idx - prev_idx
    if gap >= 2:
        months.insert(0, _month_key_offset(focus, -1))
    return months


def get_meeting_context(
    meeting_id: str,
    *,
    history_cutoff: date = DEFAULT_HISTORY_CUTOFF,
    refresh_calendar: bool = False,
) -> dict:
    meetings = ensure_fomc_calendar(
        start=DEFAULT_MEETING_RANGE_START,
        end=DEFAULT_MEETING_RANGE_END,
        force_refresh=refresh_calendar,
    )
    meetings = sorted(meetings, key=lambda m: m.end_date)

    current = None
    for m in meetings:
        if m.meeting_id == meeting_id:
            current = m
            break
    if not current:
        raise PortalError(f"Meeting not found: {meeting_id}")

    if current.end_date > history_cutoff:
        raise PortalError("Future meetings are view-only and cannot be simulated yet.")

    previous = None
    for m in meetings:
        if m.end_date < current.end_date:
            previous = m
        else:
            break

    report_months = _compute_meeting_report_months(current.end_date, previous.end_date if previous else None)
    return {
        "meeting": current.to_dict(),
        "previous_meeting": previous.to_dict() if previous else None,
        "report_months": report_months,
        "history_cutoff": history_cutoff.isoformat(),
        "notes": {
            "meeting_id_convention": "meeting_id is meeting end date (statement release day)",
            "report_months_logic": "Use 1 month if meetings are ~1 month apart; include 2 months if gap >= 2 months.",
        },
    }


def get_or_create_meeting_run(meeting_id: str, *, refresh_calendar: bool = False) -> dict:
    run = ensure_meeting_run(meeting_id)
    context = get_meeting_context(meeting_id, refresh_calendar=refresh_calendar)
    manifest = set_context(run, context)
    return manifest


def get_meeting_run(meeting_id: str) -> dict:
    run = ensure_meeting_run(meeting_id)
    return load_manifest(run)


def ensure_meeting_macro_md(meeting_id: str, *, refresh: bool = False) -> dict:
    run = ensure_meeting_run(meeting_id)
    cached = read_artifact_text(run, "macro")
    if cached and not refresh:
        return {"cached": True, "text": cached, "artifact": load_manifest(run).get("artifacts", {}).get("macro")}

    context = get_meeting_context(meeting_id)
    months = context["report_months"]

    month_payloads: list[dict] = []
    for month_key in months:
        month_payloads.append(get_macro_month(month_key, refresh=refresh))

    meeting_summary_md = None
    try:
        llm = LLMClient()
        bullets: list[str] = []
        for p in month_payloads:
            mk = p.get("month_key")
            summary = (p.get("monthly_summary_md") or "").strip()
            events = p.get("events") or []
            bullets.append(f"### {mk}\n")
            if summary:
                bullets.append(summary[:1200])
            if events:
                bullets.append("关键事件（Top 6）：")
                for evt in (events or [])[:6]:
                    date_text = (evt.get("date") or "")[:10]
                    title = evt.get("title") or ""
                    shock = evt.get("macro_shock_type") or "other"
                    score = evt.get("importance_score")
                    score_text = f"{float(score):.1f}" if score is not None else "NA"
                    bullets.append(f"- {date_text} | {shock} | 重要度:{score_text} | {title}")
            bullets.append("")

        prompt = (
            "你是FOMC会议材料撰写人。请基于给定的会议前宏观事件月报，"
            "为“本次会议窗口（可能覆盖两个月）”写一份会议级摘要（中文Markdown）。\n\n"
            "要求：\n"
            "1) 重点不是复述，而是提炼“过去两个月的变化与趋势”；\n"
            "2) 给出对通胀/增长/金融条件/风险偏好的影响路径；\n"
            "3) 用 5-8 条要点 + 一段总结；\n"
            "4) 字数约 400-700。\n\n"
            f"会议：{meeting_id}\n"
            f"覆盖月份：{', '.join(months)}\n\n"
            "材料：\n"
            + "\n".join(bullets)
        )
        meeting_summary_md = llm.chat(
            [
                {"role": "system", "content": "You write concise, high-signal FOMC meeting briefs in Chinese Markdown."},
                {"role": "user", "content": prompt},
            ]
        ).strip()
    except Exception:
        meeting_summary_md = None

    parts: list[str] = [f"# 宏观经济事件（会议窗口）\n\nMeeting: {meeting_id}\n\n覆盖月份：{', '.join(months)}\n"]
    if meeting_summary_md:
        parts.append("## 会议级摘要\n")
        parts.append(meeting_summary_md.strip() + "\n")

    for payload in month_payloads:
        month_key = payload.get("month_key")
        parts.append(f"## {month_key}\n")
        summary = payload.get("monthly_summary_md") or "（无摘要）"
        parts.append(summary.strip() + "\n")
        events = payload.get("events") or []
        if events:
            parts.append("### 事件列表\n")
            for evt in events:
                date_text = (evt.get("date") or "")[:10]
                title = evt.get("title") or ""
                shock = evt.get("macro_shock_type") or "other"
                score = evt.get("importance_score")
                score_text = f"{float(score):.1f}" if score is not None else "NA"
                parts.append(f"- {date_text} | {shock} | 重要度:{score_text} | {title}\n")
                summary_line = (evt.get("summary") or "").strip()
                if summary_line:
                    parts.append(f"  - {summary_line}\n")
        parts.append("\n")

    text = "\n".join(parts).strip() + "\n"
    artifact_meta = {"report_months": months, "source": "macro_events_db+pipeline", "has_meeting_summary": bool(meeting_summary_md)}
    artifact = write_artifact_text(run, "macro", text, meta=artifact_meta)
    return {"cached": False, "text": text, "artifact": artifact}


def _report_text_md(title: str, month_key: str, payload: Dict[str, Any]) -> str:
    llm_error = payload.get("llm_error")
    report_text = payload.get("report_text")
    headline = payload.get("headline_summary")
    lines: list[str] = [f"# {title}\n", f"## {month_key}\n"]
    if headline:
        lines.append(f"**摘要**：{headline}\n")
    if llm_error and not report_text:
        lines.append(f"**LLM 错误**：{llm_error}\n")
        return "\n".join(lines).strip() + "\n"
    if report_text:
        lines.append(report_text.strip() + "\n")
    return "\n".join(lines).strip() + "\n"


def ensure_meeting_labor_md(meeting_id: str, *, refresh: bool = False) -> dict:
    run = ensure_meeting_run(meeting_id)
    cached = read_artifact_text(run, "nfp")
    if cached and not refresh:
        return {"cached": True, "text": cached, "artifact": load_manifest(run).get("artifacts", {}).get("nfp")}

    context = get_meeting_context(meeting_id)
    months = context["report_months"]

    month_reports: list[Dict[str, Any]] = []
    for month_key in months:
        month_reports.append(generate_labor_report(month_key))

    meeting_brief_md = None
    try:
        llm = LLMClient()
        blocks: list[str] = []
        for idx, month_key in enumerate(months):
            p = month_reports[idx]
            blocks.append(f"### {month_key}\n")
            blocks.append(f"Headline: {p.get('headline_summary')}\n")
            indicators = p.get("indicators") or []
            if indicators:
                blocks.append("Key metrics:")
                for it in indicators[:8]:
                    blocks.append(f"- {it.get('name')}: {it.get('latest_value')}{it.get('units') or ''} (MoM {it.get('mom_change') or 'NA'})")
            chart_commentary = (p.get("chart_commentary") or "").strip()
            if chart_commentary:
                blocks.append(f"Chart: {chart_commentary[:500]}")
            blocks.append("")

        prompt = (
            "你是FOMC会议材料撰写人。请基于过去 1-2 个月的非农与失业率信息，"
            "写一份“本次会议的劳动力市场会议级简报”（中文Markdown）。\n\n"
            "要求：\n"
            "1) 如果覆盖两个月，必须对比两个月的变化与趋势，而非分别复述；\n"
            "2) 输出结构：核心结论（5-7条）→ 风险点 → 对政策含义（偏鹰/偏鸽因素）；\n"
            "3) 字数约 500-900。\n\n"
            f"会议：{meeting_id}\n"
            f"覆盖月份：{', '.join(months)}\n\n"
            "材料：\n"
            + "\n".join(blocks)
        )
        meeting_brief_md = llm.chat(
            [
                {"role": "system", "content": "You write concise, high-signal FOMC meeting briefs in Chinese Markdown."},
                {"role": "user", "content": prompt},
            ]
        ).strip()
    except Exception:
        meeting_brief_md = None

    parts: list[str] = [f"# 非农就业（会议级简报）\n\nMeeting: {meeting_id}\n\n覆盖月份：{', '.join(months)}\n"]
    if meeting_brief_md:
        parts.append("\n## 会议级结论\n")
        parts.append(meeting_brief_md.strip() + "\n")
    else:
        # Fallback: include per-month tool reports (may be LLM or fallback text)
        for month_key, payload in zip(months, month_reports):
            parts.append(_report_text_md("非农就业研报（NFP）", month_key, payload))

    text = "\n".join(parts).strip() + "\n"
    artifact = write_artifact_text(
        run,
        "nfp",
        text,
        meta={"report_months": months, "source": "reports_flask+meeting_prompt", "has_meeting_brief": bool(meeting_brief_md)},
    )
    return {"cached": False, "text": text, "artifact": artifact}


def ensure_meeting_cpi_md(meeting_id: str, *, refresh: bool = False) -> dict:
    run = ensure_meeting_run(meeting_id)
    cached = read_artifact_text(run, "cpi")
    if cached and not refresh:
        return {"cached": True, "text": cached, "artifact": load_manifest(run).get("artifacts", {}).get("cpi")}

    context = get_meeting_context(meeting_id)
    months = context["report_months"]

    month_reports: list[Dict[str, Any]] = []
    for month_key in months:
        month_reports.append(generate_cpi_report(month_key))

    meeting_brief_md = None
    try:
        llm = LLMClient()
        blocks: list[str] = []
        for idx, month_key in enumerate(months):
            p = month_reports[idx]
            blocks.append(f"### {month_key}\n")
            blocks.append(f"Headline: {p.get('headline_summary')}\n")
            metrics = p.get("metrics") or []
            if metrics:
                blocks.append("Key metrics:")
                for it in metrics[:8]:
                    blocks.append(f"- {it.get('name')}: {it.get('value')} (Δ {it.get('delta') or 'NA'})")
            contrib = p.get("contribution_table_md") or ""
            if contrib:
                blocks.append("Contribution highlights:")
                blocks.append(contrib[:700])
            blocks.append("")

        prompt = (
            "你是FOMC会议材料撰写人。请基于过去 1-2 个月的通胀信息（CPI/核心CPI 同比与环比，以及主要分项拉动），"
            "写一份“本次会议的通胀会议级简报”（中文Markdown）。\n\n"
            "要求：\n"
            "1) 如果覆盖两个月，必须对比两个月的变化与趋势，而非分别复述；\n"
            "2) 输出结构：核心结论（5-7条）→ 通胀路径判断（粘性/回落）→ 风险点 → 对政策含义；\n"
            "3) 字数约 500-900。\n\n"
            f"会议：{meeting_id}\n"
            f"覆盖月份：{', '.join(months)}\n\n"
            "材料：\n"
            + "\n".join(blocks)
        )
        meeting_brief_md = llm.chat(
            [
                {"role": "system", "content": "You write concise, high-signal FOMC meeting briefs in Chinese Markdown."},
                {"role": "user", "content": prompt},
            ]
        ).strip()
    except Exception:
        meeting_brief_md = None

    parts: list[str] = [f"# CPI（会议级简报）\n\nMeeting: {meeting_id}\n\n覆盖月份：{', '.join(months)}\n"]
    if meeting_brief_md:
        parts.append("\n## 会议级结论\n")
        parts.append(meeting_brief_md.strip() + "\n")
    else:
        for month_key, payload in zip(months, month_reports):
            parts.append(_report_text_md("CPI 研报", month_key, payload))

    text = "\n".join(parts).strip() + "\n"
    artifact = write_artifact_text(
        run,
        "cpi",
        text,
        meta={"report_months": months, "source": "reports_flask+meeting_prompt", "has_meeting_brief": bool(meeting_brief_md)},
    )
    return {"cached": False, "text": text, "artifact": artifact}


def ensure_meeting_taylor_md(meeting_id: str, *, refresh: bool = False) -> dict:
    run = ensure_meeting_run(meeting_id)
    cached = read_artifact_text(run, "taylor")
    if cached and not refresh:
        return {"cached": True, "text": cached, "artifact": load_manifest(run).get("artifacts", {}).get("taylor")}

    context = get_meeting_context(meeting_id)
    meeting_end = date.fromisoformat(context["meeting"]["end_date"])
    end_date = meeting_end.isoformat()
    start_date = date(meeting_end.year - 10, meeting_end.month, 1).isoformat()

    session = SessionLocal()
    try:
        payload = build_taylor_series_from_db(
            session=session,
            model=ModelType.TAYLOR,
            start_date=start_date,
            end_date=end_date,
            rho=0.0,
        )
    finally:
        session.close()

    metrics = payload.get("metrics") or {}
    series = payload.get("series") or []

    def _fmt(x) -> str:
        try:
            if x is None:
                return "—"
            v = float(x)
            if v != v:  # NaN
                return "—"
            return f"{v:.2f}%"
        except Exception:
            return "—"

    taylor_latest = metrics.get("taylorLatest")
    fed_latest = metrics.get("fedLatest")
    spread_latest = metrics.get("spread")
    if (taylor_latest is None or fed_latest is None) and series:
        try:
            last = series[-1] if isinstance(series, list) else None
            if isinstance(last, dict):
                taylor_latest = taylor_latest if taylor_latest is not None else last.get("taylor")
                fed_latest = fed_latest if fed_latest is not None else last.get("fed")
                if spread_latest is None and last.get("taylor") is not None and last.get("fed") is not None:
                    spread_latest = float(last.get("fed")) - float(last.get("taylor"))
        except Exception:
            pass

    lines = [
        "# 政策规则模型（Taylor Rule）\n",
        f"Meeting: {meeting_id}\n",
        f"- 窗口：{start_date} → {end_date}\n",
        "",
        "## 最新读数\n",
        f"- Taylor: {_fmt(taylor_latest)}\n",
        f"- EFFR: {_fmt(fed_latest)}\n",
        f"- Spread: {_fmt(spread_latest)}\n",
        "",
    ]
    text = "\n".join(lines).strip() + "\n"
    artifact = write_artifact_text(run, "taylor", text, meta={"model": "taylor", "start_date": start_date, "end_date": end_date})
    return {"cached": False, "text": text, "artifact": artifact}


def ensure_meeting_materials_all(meeting_id: str, *, refresh: bool = False) -> dict:
    results = {
        "macro": ensure_meeting_macro_md(meeting_id, refresh=refresh),
        "nfp": ensure_meeting_labor_md(meeting_id, refresh=refresh),
        "cpi": ensure_meeting_cpi_md(meeting_id, refresh=refresh),
        "taylor": ensure_meeting_taylor_md(meeting_id, refresh=refresh),
    }
    return results


def ensure_meeting_discussion_pack(meeting_id: str, *, refresh: bool = False) -> dict:
    """
    Run the meeting discussion simulation:
    - blackboard.json (facts/uncertainties)
    - stance_cards.json
    - discussion.md (public transcript)
    - votes.json
    - statement.md
    - minutes_summary.md
    """
    run = ensure_meeting_run(meeting_id)
    manifest = load_manifest(run)
    existing = manifest.get("artifacts") or {}
    if not refresh and all(k in existing for k in ["discussion", "statement", "minutes_summary", "votes", "blackboard", "stance_cards"]):
        return {
            "cached": True,
            "artifacts": {k: existing.get(k) for k in ["discussion", "statement", "minutes_summary", "votes", "blackboard", "stance_cards"]},
        }

    # Ensure upstream materials exist (meeting-level markdown artifacts).
    _ = ensure_meeting_materials_all(meeting_id, refresh=refresh)
    macro = read_artifact_text(run, "macro") or ""
    nfp = read_artifact_text(run, "nfp") or ""
    cpi = read_artifact_text(run, "cpi") or ""
    taylor = read_artifact_text(run, "taylor") or ""

    llm = LLMClient()
    blackboard = build_blackboard(meeting_id=meeting_id, source_materials={"macro": macro, "nfp": nfp, "cpi": cpi, "taylor": taylor}, llm=llm)
    crisis_mode = bool(infer_crisis_mode(blackboard))

    stance_cards: dict[str, dict] = {}
    for role in DEFAULT_ROLES:
        stance_cards[role.role] = generate_stance_card(
            meeting_id=meeting_id,
            role=role,
            blackboard=blackboard,
            crisis_mode=crisis_mode,
            llm=llm,
        )

    # Phase 2: opening statements (public)
    opening_order = [r for r in DEFAULT_ROLES if r.role in {"centrist", "hawk", "dove"}]
    opening_order = sorted(opening_order, key=lambda r: {"centrist": 0, "hawk": 1, "dove": 2}.get(r.role, 9))
    opening_speeches: list[dict] = []
    open_questions: list[str] = []
    for role in opening_order:
        speech = generate_public_speech(
            meeting_id=meeting_id,
            role=role,
            blackboard=blackboard,
            stance_card=stance_cards.get(role.role) or {},
            phase_name="opening_statements",
            chair_question=None,
            llm=llm,
        )
        opening_speeches.append(speech)
        q = str(speech.get("ask_one_question") or "").strip()
        if q:
            open_questions.append(q)

    # Add 1-2 questions from private stance cards as backup (still treated as open_questions pool).
    for role in DEFAULT_ROLES:
        sc = stance_cards.get(role.role) or {}
        for q in (sc.get("questions_to_ask") or [])[:2]:
            q = str(q or "").strip()
            if q:
                open_questions.append(q)

    # De-dupe and cap.
    seen = set()
    open_questions_dedup: list[str] = []
    for q in open_questions:
        qq = re.sub(r"\s+", " ", q).strip()
        if not qq or qq in seen:
            continue
        seen.add(qq)
        open_questions_dedup.append(qq)
    open_questions = open_questions_dedup[:10]

    round_summaries: list[dict] = []
    round_summaries.append(
        secretary_round_summary(
            meeting_id=meeting_id,
            blackboard=blackboard,
            round_name="opening_statements",
            transcript_blocks=opening_speeches,
            llm=llm,
        )
    )

    # Phase 3: chair-directed Q&A (public)
    chair_q = chair_select_questions(
        meeting_id=meeting_id,
        blackboard=blackboard,
        stance_cards=stance_cards,
        open_questions=open_questions,
        llm=llm,
        max_questions=6,
    )

    qa_speeches: list[dict] = []
    role_by_name = {r.role: r for r in DEFAULT_ROLES}
    for item in chair_q.get("directed_questions") or []:
        to_role = str(item.get("to_role") or "").strip().lower()
        question = str(item.get("question") or "").strip()
        role = role_by_name.get(to_role)
        if not role or not question:
            continue
        qa_speeches.append(
            generate_public_speech(
                meeting_id=meeting_id,
                role=role,
                blackboard=blackboard,
                stance_card=stance_cards.get(role.role) or {},
                phase_name="directed_qa",
                chair_question=question,
                llm=llm,
            )
        )

    round_summaries.append(
        secretary_round_summary(
            meeting_id=meeting_id,
            blackboard=blackboard,
            round_name="directed_qa",
            transcript_blocks=qa_speeches,
            llm=llm,
        )
    )

    # Phase 4: packages + vote
    packages = chair_propose_packages(meeting_id=meeting_id, blackboard=blackboard, stance_cards=stance_cards, llm=llm)
    pkgs_list = packages.get("packages") or []

    package_views: list[dict] = []
    votes: list[dict] = []
    for role in opening_order:
        package_views.append(
            generate_package_preference(
                meeting_id=meeting_id,
                role=role,
                blackboard=blackboard,
                stance_card=stance_cards.get(role.role) or {},
                packages=pkgs_list,
                llm=llm,
            )
        )
        votes.append(
            generate_vote(
                meeting_id=meeting_id,
                role=role,
                blackboard=blackboard,
                stance_card=stance_cards.get(role.role) or {},
                packages=pkgs_list,
                crisis_mode=crisis_mode,
                llm=llm,
            )
        )

    drafts = chair_write_statement_and_minutes(
        meeting_id=meeting_id,
        blackboard=blackboard,
        votes=votes,
        round_summaries=round_summaries,
        llm=llm,
    )

    discussion_md = render_discussion_markdown(
        meeting_id=meeting_id,
        blackboard=blackboard,
        crisis_mode=crisis_mode,
        stance_cards=stance_cards,
        opening_speeches=opening_speeches,
        chair_q=chair_q,
        qa_speeches=qa_speeches,
        packages=packages,
        package_views=package_views,
        votes=votes,
    )

    artifacts: dict[str, Any] = {}
    artifacts["blackboard"] = write_artifact_json(run, "blackboard", blackboard, meta={"kind": "blackboard"})
    artifacts["stance_cards"] = write_artifact_json(run, "stance_cards", stance_cards, meta={"kind": "stance_cards"})
    artifacts["round_summaries"] = write_artifact_json(run, "round_summaries", {"rounds": round_summaries}, meta={"kind": "round_summaries"})
    artifacts["packages"] = write_artifact_json(run, "packages", packages, meta={"kind": "packages"})
    artifacts["votes"] = write_artifact_json(run, "votes", {"votes": votes}, meta={"kind": "votes", "crisis_mode": crisis_mode})
    artifacts["discussion"] = write_artifact_text(run, "discussion", discussion_md, meta={"kind": "discussion", "crisis_mode": crisis_mode})
    artifacts["statement"] = write_artifact_text(run, "statement", drafts["statement_md"], meta={"kind": "statement"})
    artifacts["minutes_summary"] = write_artifact_text(run, "minutes_summary", drafts["minutes_summary_md"], meta={"kind": "minutes_summary"})

    return {"cached": False, "artifacts": artifacts}


def get_meeting_discussion_cached(meeting_id: str) -> dict:
    run = ensure_meeting_run(meeting_id)
    manifest = load_manifest(run)
    text = read_artifact_text(run, "discussion")
    artifact = (manifest.get("artifacts") or {}).get("discussion")
    html_text = _render_markdown(text) if text else None
    return {
        "cached": text is not None,
        "text": text,
        "html": html_text,
        "artifact": artifact,
        "blackboard": read_artifact_json(run, "blackboard"),
        "stance_cards": read_artifact_json(run, "stance_cards"),
        "round_summaries": read_artifact_json(run, "round_summaries"),
        "packages": read_artifact_json(run, "packages"),
        "votes": read_artifact_json(run, "votes"),
        "manifest": {"meeting_id": meeting_id},
    }


def get_meeting_decision_cached(meeting_id: str) -> dict:
    run = ensure_meeting_run(meeting_id)
    manifest = load_manifest(run)
    statement = read_artifact_text(run, "statement")
    minutes = read_artifact_text(run, "minutes_summary")
    votes = read_artifact_json(run, "votes")
    return {
        "cached": bool(statement or minutes or votes),
        "statement": statement,
        "statement_html": _render_markdown(statement) if statement else None,
        "minutes_summary": minutes,
        "minutes_summary_html": _render_markdown(minutes) if minutes else None,
        "votes": votes,
        "artifacts": {
            "statement": (manifest.get("artifacts") or {}).get("statement"),
            "minutes_summary": (manifest.get("artifacts") or {}).get("minutes_summary"),
            "votes": (manifest.get("artifacts") or {}).get("votes"),
        },
        "manifest": {"meeting_id": meeting_id},
    }


def start_meeting_discussion_job(*, meeting_id: str, refresh: bool = False) -> Dict[str, Any]:
    job = _create_job("meeting-discussion")

    def _run(writer: _JobWriter, **kwargs: Any) -> None:
        mid = str(kwargs["meeting_id"])
        r = bool(kwargs.get("refresh"))
        writer.write(f"meeting_id={mid}\n")
        writer.write(f"refresh={r}\n")

        # Ensure manifest exists (records context).
        _ = get_or_create_meeting_run(mid)

        out = ensure_meeting_discussion_pack(mid, refresh=r)
        with _JOB_LOCK:
            job.result = {"meeting_id": mid, "cached": out.get("cached")}
        writer.write("done\n")

    thread = threading.Thread(
        target=_run_job,
        args=(job, _run, {"meeting_id": meeting_id, "refresh": refresh}),
        daemon=True,
    )
    thread.start()
    return {"job_id": job.id}


def get_meeting_material_cached(meeting_id: str, kind: str) -> dict:
    run = ensure_meeting_run(meeting_id)
    text = read_artifact_text(run, kind)
    manifest = load_manifest(run)
    artifact = (manifest.get("artifacts") or {}).get(kind)
    return {
        "cached": text is not None,
        "text": text,
        "html": _render_markdown(text) if text else None,
        "artifact": artifact,
        "manifest": {"meeting_id": meeting_id},
    }


def start_meeting_material_job(*, meeting_id: str, kind: str, refresh: bool = False) -> Dict[str, Any]:
    """
    Run meeting material generation in a background job, so the UI can poll progress.

    kind: macro|nfp|cpi|taylor|all
    """
    kind = (kind or "").lower().strip()
    if kind not in {"macro", "nfp", "cpi", "taylor", "all"}:
        raise PortalError(f"Unknown material kind: {kind}")

    job = _create_job(f"meeting-material:{kind}")

    def _run(writer: _JobWriter, **kwargs: Any) -> None:
        mid = str(kwargs["meeting_id"])
        k = str(kwargs["kind"])
        r = bool(kwargs.get("refresh"))
        writer.write(f"meeting_id={mid}\n")
        writer.write(f"kind={k} refresh={r}\n")

        # Ensure manifest exists (records context).
        _ = get_or_create_meeting_run(mid)

        if k == "macro":
            out = ensure_meeting_macro_md(mid, refresh=r)
        elif k == "nfp":
            out = ensure_meeting_labor_md(mid, refresh=r)
        elif k == "cpi":
            out = ensure_meeting_cpi_md(mid, refresh=r)
        elif k == "taylor":
            out = ensure_meeting_taylor_md(mid, refresh=r)
        else:
            out = ensure_meeting_materials_all(mid, refresh=r)

        with _JOB_LOCK:
            job.result = {"meeting_id": mid, "kind": k, "cached": out.get("cached") if isinstance(out, dict) else None}

        writer.write("done\n")

    thread = threading.Thread(
        target=_run_job,
        args=(job, _run, {"meeting_id": meeting_id, "kind": kind, "refresh": refresh}),
        daemon=True,
    )
    thread.start()
    return {"job_id": job.id}


def list_fomc_meetings(
    *,
    start: date = DEFAULT_MEETING_RANGE_START,
    end: date = DEFAULT_MEETING_RANGE_END,
    history_cutoff: date = DEFAULT_HISTORY_CUTOFF,
    refresh: bool = False,
) -> dict:
    meetings = ensure_fomc_calendar(start=start, end=end, force_refresh=refresh)
    historical: list[dict] = []
    future: list[dict] = []
    for m in meetings:
        payload = m.to_dict()
        payload["status"] = "historical" if m.end_date <= history_cutoff else "future"
        if payload["status"] == "historical":
            historical.append(payload)
        else:
            future.append(payload)

    historical.sort(key=lambda x: x["end_date"])
    future.sort(key=lambda x: x["end_date"])
    newest_historical_id = historical[-1]["meeting_id"] if historical else None
    for item in historical:
        item["is_newest_historical"] = item["meeting_id"] == newest_historical_id

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "history_cutoff": history_cutoff.isoformat(),
        "historical": historical,
        "future": future,
    }


def meetings_timeline(
    *,
    start: date = DEFAULT_MEETING_RANGE_START,
    end: date = DEFAULT_MEETING_RANGE_END,
    history_cutoff: date = DEFAULT_HISTORY_CUTOFF,
    refresh_calendar: bool = False,
    k: int = 2,
    m_hold: int = 3,
    delta_threshold_bps: float = 1.0,
) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        return build_meetings_timeline(
            session=session,
            start=start,
            end=end,
            history_cutoff=history_cutoff,
            refresh_calendar=refresh_calendar,
            k=k,
            m_hold=m_hold,
            delta_threshold_bps=delta_threshold_bps,
        )
    finally:
        session.close()


def get_fomc_meeting(
    meeting_id: str,
    *,
    start: date = DEFAULT_MEETING_RANGE_START,
    end: date = DEFAULT_MEETING_RANGE_END,
    refresh: bool = False,
) -> dict:
    meetings = ensure_fomc_calendar(start=start, end=end, force_refresh=refresh)
    for m in meetings:
        if m.meeting_id == meeting_id:
            return m.to_dict()
    raise PortalError(f"Meeting not found: {meeting_id}")


def _call_flask_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke an existing Flask endpoint inside the same process."""
    with reports_app.test_client() as client:
        resp = client.post(path, json=payload)
        return _handle_flask_response(resp)


def _call_flask_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """GET wrapper for Flask endpoints."""
    with reports_app.test_client() as client:
        resp = client.get(path, query_string=params)
        return _handle_flask_response(resp)


def _call_flask_pdf(path: str, payload: Dict[str, Any]) -> tuple[bytes, Dict[str, str]]:
    """Call a Flask PDF endpoint and return bytes + headers."""
    with reports_app.test_client() as client:
        resp = client.post(path, json=payload)
        if resp.status_code >= 400:
            message = resp.data.decode("utf-8") or f"HTTP {resp.status_code}"
            raise PortalError(message)
        headers = {k: v for k, v in resp.headers.items()}
        return resp.data, headers


def _handle_flask_response(resp):
    if resp.status_code >= 400:
        try:
            detail = resp.get_json() or {}
        except Exception:
            detail = {}
        message = detail.get("error") or resp.data.decode("utf-8") or f"HTTP {resp.status_code}"
        raise PortalError(message)
    try:
        return resp.get_json()  # type: ignore[return-value]
    except Exception as exc:
        raise PortalError(f"Failed to parse response: {exc}")


def _render_markdown(md_text: str | None) -> str | None:
    """Render markdown with auto-linked URLs."""
    if not md_text:
        return None
    return markdown2.markdown(md_text, extras=["autolink", "break-on-newline", "fenced-code-blocks"])


def generate_labor_report(month: str) -> Dict[str, Any]:
    """Generate labor-market report payload via the existing Flask app."""
    return _call_flask_json("/api/labor-market/report", {"report_month": month})


def generate_cpi_report(month: str) -> Dict[str, Any]:
    """Generate CPI report payload via the existing Flask app."""
    return _call_flask_json("/api/cpi/report", {"report_month": month})


def export_labor_pdf(month: str) -> tuple[bytes, Dict[str, str]]:
    """Generate labor report PDF via Flask."""
    report = generate_labor_report(month)
    return _call_flask_pdf("/api/labor-market/report.pdf", {"report_data": report})


def export_cpi_pdf(month: str) -> tuple[bytes, Dict[str, str]]:
    """Generate CPI report PDF via Flask."""
    report = generate_cpi_report(month)
    return _call_flask_pdf("/api/cpi/report.pdf", {"report_data": report})


def get_macro_month(month_key: str, refresh: bool = False) -> Dict[str, Any]:
    """
    Fetch macro events for a month; refresh will trigger collection if needed.
    """
    conn = get_connection(MACRO_EVENTS_DB_PATH)
    try:
        record_row = get_month_record(conn, month_key, "macro")
        record = dict(record_row) if record_row else None
        if refresh or not record or not record.get("monthly_summary"):
            events = ensure_month_events(month_key, db_path=MACRO_EVENTS_DB_PATH, force_refresh=refresh)
            refreshed = get_month_record(conn, month_key, "macro")
            record = dict(refreshed) if refreshed else None
        else:
            events = get_events_for_month(conn, month_key, "macro")
        summary_md = record["monthly_summary"] if record else None
        summary_html = _render_markdown(summary_md)
        events = [_shape_event(e) for e in events]
        try:
            events = sorted(events, key=lambda e: e.get("date") or "")
        except Exception:
            pass
        payload = {
            "month_key": month_key,
            "status": record["status"] if record else "unknown",
            "last_refreshed_at": record["last_refreshed_at"] if record else None,
            "num_events": record["num_events"] if record else len(events),
            "events": events,
            "monthly_summary_md": summary_md,
            "monthly_summary_html": summary_html,
        }
        return payload
    finally:
        conn.close()


def list_macro_months(order: str = "desc") -> List[Dict[str, Any]]:
    """Return months list from DB for quick browsing."""
    conn = get_connection(MACRO_EVENTS_DB_PATH)
    try:
        direction = "DESC" if order.lower() == "desc" else "ASC"
        cur = conn.execute(
            f"SELECT * FROM months ORDER BY month_key {direction};"
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        conn.close()


def refresh_macro_month(month_key: str) -> Dict[str, Any]:
    """Force refresh of a given month and return the month payload."""
    return get_macro_month(month_key, refresh=True)


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


def export_macro_pdf(month_key: str, refresh: bool = False) -> tuple[bytes, Dict[str, str]]:
    """
    Render macro events month into a PDF using Playwright (if available).
    """
    data = get_macro_month(month_key, refresh=refresh)
    summary_html = data.get("monthly_summary_html") or "<p>无月报摘要</p>"
    url_title_map: Dict[str, str] = {}
    for evt in data.get("events") or []:
        titles = evt.get("sources") or []
        urls = evt.get("source_urls") or []
        for idx, url in enumerate(urls):
            if not url:
                continue
            title = titles[idx] if idx < len(titles) else None
            url_title_map[url] = title or evt.get("title") or url

    def link_chips(html_str: str) -> str:
        def autolink(text: str) -> str:
            return re.sub(
                r"(https?://[^\s<]+)",
                lambda m: f"<a href=\"{html.escape(m.group(1))}\" target=\"_blank\" rel=\"noopener noreferrer\">{html.escape(m.group(1))}</a>",
                text or "",
            )

        def patch_anchor(match: re.Match) -> str:
            tag = match.group(0)
            cls_match = re.search(r'class=["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
            if cls_match:
                classes = cls_match.group(1)
                if "link-chip" not in classes.split():
                    tag = tag.replace(cls_match.group(0), f'class="{classes} link-chip"')
            else:
                tag = tag.replace("<a", "<a class=\"link-chip\"", 1)
            if "target=" not in tag:
                tag = tag.replace("<a", "<a target=\"_blank\" rel=\"noopener noreferrer\"", 1)
            elif "rel=" not in tag:
                tag = tag.replace("target=", "rel=\"noopener noreferrer\" target=", 1)
            return tag
        def shorten(href: str) -> str:
            try:
                parsed = html.escape(href)
                from urllib.parse import urlparse
                parts = urlparse(href)
                host = parts.hostname or href
                path = (parts.path or "")[:24]
                path = (path + "…") if parts.path and len(parts.path) > 24 else path
                return f"{host}{path}"
            except Exception:
                safe = html.escape(href)
                return safe if len(safe) <= 42 else safe[:38] + "…"

        html_processed = autolink(html_str or "")

        def normalize(match: re.Match) -> str:
            raw = match.group(0)
            href_match = re.search(r'href=["\']([^"\']+)["\']', raw, flags=re.IGNORECASE)
            href = href_match.group(1) if href_match else ""
            label = url_title_map.get(href) or shorten(href)
            return f"<a class='link-chip' href='{html.escape(href)}' target='_blank' rel='noopener noreferrer'>{html.escape(label)}</a>"

        return re.sub(r"<a\b[^>]*>.*?</a>", normalize, html_processed, flags=re.IGNORECASE | re.DOTALL)

    def source_chips(evt: Dict[str, Any]) -> str:
        titles = evt.get("sources") or []
        urls = evt.get("source_urls") or []
        chips: List[str] = []
        for idx, title in enumerate(titles):
            url = urls[idx] if idx < len(urls) else ""
            label = title or url or "来源"
            safe_label = html.escape(str(label))
            href = html.escape(str(url)) if url else "#"
            chips.append(f"<a class='source-chip' href='{href}' target='_blank'>{safe_label}</a>")
        return "".join(chips)

    events_html = "".join(
        f"""
        <div class='timeline-item'>
          <div class='timeline-dot'></div>
          <div class='timeline-card'>
            <div class='event-meta'>
              <span class='pill date'>{html.escape(e.get('date') or '')}</span>
              <span class='pill kind'>{html.escape((e.get('macro_shock_type') or 'other'))}</span>
              <span class='pill channel'>{', '.join(e.get('impact_channel') or [])}</span>
              <span class='pill score'>Score {e.get('importance_score') or ''}</span>
            </div>
            <div class='event-title'>{html.escape(e.get('title') or '')}</div>
            <div class='event-summary'>{html.escape(e.get('summary') or '')}</div>
            <div class='event-sources'>{source_chips(e)}</div>
          </div>
        </div>
        """
        for e in data.get("events") or []
    )
    css = """
    <style>
      body {
        font-family: "Times New Roman", "KaiTi", "PingFang SC", serif;
        margin: 18px;
        background: #f3f9f7;
        color: #0b1f1d;
        font-size: 14px;
        line-height: 1.6;
      }
      .page {
        max-width: 760px;
        margin: 0 auto;
      }
      .header {
        padding: 14px 16px;
        border-radius: 14px;
        background: linear-gradient(135deg, #0f3b3d, #0f766e);
        color: #ecfeff;
        box-shadow: 0 14px 30px rgba(15,118,110,0.28);
        margin-bottom: 14px;
      }
      .header h1 { margin: 0 0 6px; font-size: 20px; }
      .pill { padding: 4px 10px; border-radius: 10px; font-size: 12px; font-weight: 700; display: inline-flex; align-items: center; gap: 6px; }
      .pill.date { background: rgba(12,74,110,0.14); color: #0b1f1d; }
      .pill.kind { background: rgba(12,74,110,0.12); color: #0b1f1d; }
      .pill.channel { background: rgba(79,209,197,0.15); color: #0b1f1d; }
      .pill.score { background: rgba(239,68,68,0.16); color: #b91c1c; }
      .section-title { margin: 18px 0 10px; font-size: 16px; letter-spacing: 0.2px; color: #0b1f1d; }
      .card {
        border: 1px solid #d1e4de;
        border-radius: 14px;
        padding: 14px 16px;
        background: #fff;
        box-shadow: 0 12px 30px rgba(15,118,110,0.14);
      }
      .timeline { position: relative; padding-left: 14px; margin-top: 8px; }
      .timeline::before { content: ""; position: absolute; left: 6px; top: 0; bottom: 0; width: 2px; background: linear-gradient(to bottom, #99f6e4, #d1fae5); }
      .timeline-item { position: relative; margin-bottom: 12px; }
      .timeline-dot { position: absolute; left: -1px; top: 10px; width: 10px; height: 10px; border-radius: 50%; background: linear-gradient(135deg, #0f3b3d, #38bdf8); border: 2px solid #fff; box-shadow: 0 0 0 4px rgba(56,189,248,0.16); }
      .timeline-card {
        margin-left: 12px;
        border: 1px solid #d1e4de;
        border-radius: 12px;
        padding: 12px;
        background: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(236,254,255,0.9));
        box-shadow: 0 8px 20px rgba(15,118,110,0.12);
      }
      .event-meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 6px; color: #0b1f1d; }
      .event-title { font-weight: 800; margin-bottom: 6px; color: #0f172a; }
      .event-summary { color: #0b1f1d; line-height: 1.6; }
      .event-sources { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px; }
      .source-chip {
        padding: 6px 10px;
        border-radius: 999px;
        background: rgba(56,189,248,0.12);
        color: #0b1f1d;
        text-decoration: none;
        font-size: 12px;
        border: 1px solid rgba(56,189,248,0.24);
      }
      .summary-chip a { color: inherit; text-decoration: none; }
      .summary-card a {
        display: inline-block;
        margin: 2px 4px 2px 0;
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(56,189,248,0.12);
        color: #0b1f1d;
        text-decoration: none;
        border: 1px solid rgba(56,189,248,0.22);
      }
      .link-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(56,189,248,0.12);
        color: #0b1f1d;
        text-decoration: none;
        border: 1px solid rgba(56,189,248,0.22);
        margin: 2px 4px 2px 0;
        font-size: 12px;
      }
    </style>
    """
    pdf_html = f"""
    <html>
      <head>
        <meta charset='utf-8' />
        {css}
      </head>
      <body>
        <div class='page'>
          <div class='header'>
            <div class='pill'>宏观事件月报</div>
            <h1>{data.get('month_key')}</h1>
            <div>事件 {data.get('num_events') or len(data.get('events') or [])} 条</div>
          </div>
          <div class='card'>
            <div class='section-title'>月报摘要</div>
            <div class='summary-card'>{link_chips(summary_html)}</div>
          </div>
          <h2 class='section-title'>事件时间线</h2>
          <div class='card'>
            <div class='timeline'>{events_html or '<p class=\"muted\">暂无事件</p>'}</div>
          </div>
        </div>
      </body>
    </html>
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PortalError("缺少 playwright 依赖，无法导出 PDF。请先安装：pip install playwright && playwright install chromium") from exc

    header_template = """
    <style>
      .pdf-head { font-family: 'Times New Roman','KaiTi',serif; font-size: 12px; width: 100%; padding: 10px 22px 8px; color: #0f172a; display:flex; justify-content: space-between; align-items: center; box-sizing:border-box; }
      .pdf-head .brand { display:flex; align-items:center; gap:12px; font-weight:700; letter-spacing:0.3px; }
      .pdf-head .icon { width:30px; height:30px; border-radius:10px; background:linear-gradient(135deg,#0f766e,#0ea5e9); position:relative; box-shadow:0 8px 20px rgba(14,165,233,0.2), inset 0 1px 0 rgba(255,255,255,0.18); display:grid; place-items:center; }
      .pdf-head .icon::after { content:\"\"; position:absolute; inset:4px; border-radius:8px; border:1px solid rgba(255,255,255,0.3); box-shadow:inset 0 0 0 1px rgba(0,0,0,0.06); }
      .pdf-head .icon span { position:relative; z-index:1; color:#e0f2fe; font-size:13px; font-weight:800; font-family:'Times New Roman', serif; letter-spacing:0.4px; }
      .pdf-head .tagline { font-weight:650; color:#0f172a; font-size: 11.5px; }
    </style>
    <div class="pdf-head">
      <div class="brand"><span class="icon"><span>M</span></span><span>Macro Pulse · 事件月报</span></div>
      <div class="tagline">冲击脉络 · 风险前瞻</div>
    </div>
    """
    footer_template = """
    <style>
      .pdf-foot { font-family: 'Times New Roman','KaiTi',serif; font-size:11.5px; width:100%; padding:8px 22px 8px; color:#0f172a; text-align:right; box-sizing:border-box; }
    </style>
    <div class="pdf-foot">第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页</div>
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--export-tagged-pdf"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(pdf_html, wait_until="load")
        try:
            session = page.context.new_cdp_session(page)
            mm_to_inch = 0.0393701
            result = session.send("Page.printToPDF", {
                "printBackground": True,
                "displayHeaderFooter": True,
                "headerTemplate": header_template,
                "footerTemplate": footer_template,
                "marginTop": 20 * mm_to_inch,
                "marginBottom": 18 * mm_to_inch,
                "marginLeft": 16 * mm_to_inch,
                "marginRight": 16 * mm_to_inch,
                "paperWidth": 8.27,
                "paperHeight": 11.69,
                "generateTaggedPDF": True
            })
            pdf_bytes = base64.b64decode(result.get("data", b""))
        except Exception:
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template=header_template,
                footer_template=footer_template,
                margin={"top": "20mm", "bottom": "18mm", "left": "16mm", "right": "16mm"}
            )
        browser.close()
    return pdf_bytes, {"Content-Disposition": f'attachment; filename="macro_events_{month_key}.pdf"'}


# --- Indicator data browser helpers ---


def list_indicator_tree() -> Dict[str, Any]:
    """Fetch indicator hierarchy for the data browser."""
    return _call_flask_get("/api/indicators", {})


def fetch_indicator_data(indicator_id: int, date_range: str = "3Y") -> Dict[str, Any]:
    """Fetch indicator time series for the data browser."""
    return _call_flask_get("/api/chart-data", {"indicator_id": indicator_id, "date_range": date_range})


# --- Database management (jobs + health) ---


@dataclass
class DbJob:
    id: str
    kind: str
    status: str = "queued"  # queued|running|success|error
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    result: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
            "logs": self.logs[-800:],
        }


_JOB_LOCK = threading.Lock()
_JOBS: Dict[str, DbJob] = {}


class _JobWriter(io.TextIOBase):
    def __init__(self, job: DbJob):
        self.job = job
        self._buffer = ""

    def write(self, s: str) -> int:  # type: ignore[override]
        if not s:
            return 0
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            with _JOB_LOCK:
                self.job.logs.append(line.rstrip("\r"))
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        if self._buffer:
            with _JOB_LOCK:
                self.job.logs.append(self._buffer.rstrip("\r"))
            self._buffer = ""


def _create_job(kind: str) -> DbJob:
    job = DbJob(id=str(uuid.uuid4()), kind=kind)
    with _JOB_LOCK:
        _JOBS[job.id] = job
    return job


def get_db_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        return job.as_dict() if job else None


def _run_job(job: DbJob, fn, kwargs: Dict[str, Any]) -> None:
    job.started_at = time.time()
    job.status = "running"
    writer = _JobWriter(job)

    try:
        fn(writer, **kwargs)
        writer.flush()
        job.status = "success"
    except Exception as exc:
        writer.flush()
        job.status = "error"
        job.error = str(exc)
        with _JOB_LOCK:
            job.logs.append(f"[error] {exc}")
    finally:
        job.finished_at = time.time()


def start_sync_indicators_job(
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    requests_per_minute: int = 30,
    default_start_date: str = "2010-01-01",
    full_refresh: bool = False,
) -> Dict[str, Any]:
    job = _create_job("sync-indicators")

    def _sync(writer: _JobWriter, **kwargs: Any) -> None:
        excel_path = REPO_ROOT / "docs" / "US Economic Indicators with FRED Codes.xlsx"
        writer.write(f"DB: {MAIN_DB_PATH}\n")
        writer.write(f"Excel: {excel_path}\n")
        session = SessionLocal()
        try:
            pipeline = IndicatorSyncPipeline(
                session=session,
                excel_path=str(excel_path),
                requests_per_minute=int(kwargs["requests_per_minute"]),
                default_start_date=str(kwargs["default_start_date"]),
                start_date=kwargs.get("start_date"),
                end_date=kwargs.get("end_date"),
                full_refresh=bool(kwargs.get("full_refresh")),
            )
            # Capture pipeline prints into the job log.
            old_stdout = __import__("sys").stdout
            old_stderr = __import__("sys").stderr
            try:
                __import__("sys").stdout = writer  # type: ignore[assignment]
                __import__("sys").stderr = writer  # type: ignore[assignment]
                pipeline.run()
            finally:
                __import__("sys").stdout = old_stdout
                __import__("sys").stderr = old_stderr
        finally:
            session.close()

    thread = threading.Thread(
        target=_run_job,
        args=(job, _sync, {
            "start_date": start_date,
            "end_date": end_date,
            "requests_per_minute": requests_per_minute,
            "default_start_date": default_start_date,
            "full_refresh": full_refresh,
        }),
        daemon=True,
    )
    thread.start()
    return {"job_id": job.id}


def start_refresh_indicator_job(
    *,
    indicator_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    requests_per_minute: int = 30,
    default_start_date: str = "2010-01-01",
    full_refresh: bool = False,
) -> Dict[str, Any]:
    job = _create_job("refresh-indicator")

    def _refresh(writer: _JobWriter, **kwargs: Any) -> None:
        session = SessionLocal()
        try:
            indicator = session.query(EconomicIndicator).filter(EconomicIndicator.id == int(kwargs["indicator_id"])).first()
            if indicator is None:
                raise PortalError(f"Indicator not found: {kwargs['indicator_id']}")
            writer.write(f"Refreshing {indicator.name} ({indicator.code})\n")
            updater = IndicatorDataUpdater(
                session,
                requests_per_minute=int(kwargs["requests_per_minute"]),
                default_start_date=str(kwargs["default_start_date"]),
            )
            old_stdout = __import__("sys").stdout
            old_stderr = __import__("sys").stderr
            try:
                __import__("sys").stdout = writer  # type: ignore[assignment]
                __import__("sys").stderr = writer  # type: ignore[assignment]
                inserted = updater.update_indicator_data(
                    indicator,
                    start_date=kwargs.get("start_date"),
                    end_date=kwargs.get("end_date"),
                    full_refresh=bool(kwargs.get("full_refresh")),
                )
            finally:
                __import__("sys").stdout = old_stdout
                __import__("sys").stderr = old_stderr

            with _JOB_LOCK:
                job.result = {"inserted": inserted, "indicator_id": indicator.id, "code": indicator.code}
            writer.write(f"Done. Inserted {inserted} rows.\n")
        finally:
            session.close()

    thread = threading.Thread(
        target=_run_job,
        args=(job, _refresh, {
            "indicator_id": indicator_id,
            "start_date": start_date,
            "end_date": end_date,
            "requests_per_minute": requests_per_minute,
            "default_start_date": default_start_date,
            "full_refresh": full_refresh,
        }),
        daemon=True,
    )
    thread.start()
    return {"job_id": job.id}


def get_indicator_health(indicator_id: int) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        indicator = (
            session.query(EconomicIndicator)
            .filter(EconomicIndicator.id == indicator_id)
            .first()
        )
        if indicator is None:
            raise PortalError("未找到指定的指标")

        category_name = None
        if indicator.category_id:
            category = session.query(IndicatorCategory).filter(IndicatorCategory.id == indicator.category_id).first()
            category_name = category.name if category else None

        min_date = (
            session.query(EconomicDataPoint.date)
            .filter(EconomicDataPoint.indicator_id == indicator_id)
            .order_by(EconomicDataPoint.date.asc())
            .limit(1)
            .scalar()
        )
        max_date = (
            session.query(EconomicDataPoint.date)
            .filter(EconomicDataPoint.indicator_id == indicator_id)
            .order_by(EconomicDataPoint.date.desc())
            .limit(1)
            .scalar()
        )
        count = (
            session.query(EconomicDataPoint.id)
            .filter(EconomicDataPoint.indicator_id == indicator_id)
            .count()
        )

        missing_months: List[str] = []
        missing_month_count = 0
        freq = (indicator.frequency or "").lower()

        def month_key(dt: datetime) -> str:
            return dt.strftime("%Y-%m")

        if min_date and max_date and ("month" in freq or "monthly" in freq or freq == ""):
            # Fast month coverage check: distinct YYYY-MM in SQL to avoid loading all daily rows.
            from sqlalchemy import func

            rows = (
                session.query(func.strftime("%Y-%m", EconomicDataPoint.date))
                .filter(EconomicDataPoint.indicator_id == indicator_id)
                .distinct()
                .all()
            )
            observed = {r[0] for r in rows if r and r[0]}
            start = datetime(min_date.year, min_date.month, 1)
            end = datetime(max_date.year, max_date.month, 1)
            expected: List[str] = []
            cursor = start
            while cursor <= end:
                expected.append(month_key(cursor))
                year = cursor.year + (cursor.month // 12)
                month = 1 if cursor.month == 12 else cursor.month + 1
                cursor = datetime(year, month, 1)
            missing = [m for m in expected if m not in observed]
            missing_month_count = len(missing)
            missing_months = missing[:24]

        return {
            "id": indicator.id,
            "name": indicator.name,
            "code": indicator.code,
            "category": category_name,
            "frequency": indicator.frequency,
            "units": indicator.units,
            "fred_url": indicator.fred_url,
            "last_updated": indicator.last_updated.isoformat() if indicator.last_updated else None,
            "min_date": min_date.isoformat() if min_date else None,
            "max_date": max_date.isoformat() if max_date else None,
            "count": count,
            "missing_month_count": missing_month_count,
            "missing_months": missing_months,
        }
    finally:
        session.close()
