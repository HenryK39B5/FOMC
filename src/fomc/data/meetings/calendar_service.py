from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import re
from pathlib import Path
from typing import Iterable, List, Optional

import time
import requests

from fomc.config.paths import MEETINGS_DIR


FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_HISTORICAL_YEAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class FomcMeeting:
    meeting_id: str
    start_date: date
    end_date: date
    year: int
    label: str
    source_url: str = FED_CALENDAR_URL

    def to_dict(self) -> dict:
        return {
            "meeting_id": self.meeting_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "year": self.year,
            "label": self.label,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "FomcMeeting":
        return cls(
            meeting_id=str(payload["meeting_id"]),
            start_date=date.fromisoformat(payload["start_date"]),
            end_date=date.fromisoformat(payload["end_date"]),
            year=int(payload["year"]),
            label=str(payload["label"]),
            source_url=str(payload.get("source_url") or FED_CALENDAR_URL),
        )


def _normalize_dash(text: str) -> str:
    return (text or "").replace("\u2013", "-").replace("\u2014", "-")


def _safe_int(text: str) -> Optional[int]:
    try:
        return int(text)
    except Exception:
        return None


def _compute_label(year: int, month_name: str, start_day: int, end_year: int, end_month: int, end_day: int) -> str:
    month_display = month_name.capitalize()
    if start_day == end_day and year == end_year and MONTHS[month_name.lower()] == end_month:
        return f"{month_display} {start_day}, {year}"
    if year == end_year and MONTHS[month_name.lower()] == end_month:
        return f"{month_display} {start_day}-{end_day}, {year}"
    end_month_display = [k.capitalize() for k, v in MONTHS.items() if v == end_month][0]
    return f"{month_display} {start_day}-{end_month_display} {end_day}, {year}"


def fetch_fomc_calendar_html(*, url: str = FED_CALENDAR_URL, timeout: int = 45) -> str:
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "FOMC-Portal/0.1"})
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            last_exc = exc
            time.sleep(0.8 * (attempt + 1))
    raise last_exc or RuntimeError("Failed to fetch calendar HTML")


def fetch_fomc_historical_year_html(*, year: int, timeout: int = 45) -> str:
    url = FED_HISTORICAL_YEAR_URL.format(year=year)
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "FOMC-Portal/0.1"})
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            last_exc = exc
            time.sleep(0.9 * (attempt + 1))
    raise last_exc or RuntimeError(f"Failed to fetch historical HTML for {year}")


def parse_fomc_historical_year_meetings_from_html(
    html_text: str,
    *,
    year: int,
    source_url: str,
) -> List[FomcMeeting]:
    """
    Parse historical year page (e.g., fomchistorical2010.htm).

    These pages list each meeting as a panel with a heading like:
    'January 26-27 Meeting - 2010'
    """

    def build_meeting_from_heading(text: str) -> Optional[FomcMeeting]:
        t = _normalize_dash(text or "")
        t = re.sub(r"\s+", " ", t).strip()
        # Most common format: "January 26-27 Meeting - 2010"
        m = re.match(
            r"^(?P<month>[A-Za-z]+)\s+(?P<d1>\d{1,2})(?:\s*-\s*(?P<d2>\d{1,2}))?\s+Meeting\s*-\s*(?P<y>\d{4})$",
            t,
            flags=re.IGNORECASE,
        )
        if not m:
            return None
        y = int(m.group("y"))
        if y != year:
            return None
        month_name = m.group("month")
        month_num = MONTHS.get(month_name.lower())
        if not month_num:
            return None
        d1 = _safe_int(m.group("d1"))
        d2 = _safe_int(m.group("d2")) if m.group("d2") else d1
        if not d1 or not d2:
            return None

        start_dt = date(year, month_num, d1)
        end_year = year
        end_month = month_num
        if d2 < d1:
            end_month = month_num + 1 if month_num < 12 else 1
            end_year = year if month_num < 12 else year + 1
        end_dt = date(end_year, end_month, d2)

        meeting_id = end_dt.isoformat()
        label = _compute_label(year, month_name, d1, end_year, end_month, d2)
        return FomcMeeting(
            meeting_id=meeting_id,
            start_date=start_dt,
            end_date=end_dt,
            year=year,
            label=label,
            source_url=source_url,
        )

    headings: list[str] = []
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html_text, "html.parser")
        # Different historical-year pages use different markup:
        # - 2010: <div class="panel-heading"><h5>January ... Meeting - 2010</h5></div>
        # - 2011+: <h5 class="panel-heading ...">January ... Meeting - 2011</h5>
        # So we simply scan all h5/h4 headings and parse those that match.
        for tag in soup.select("h5, h4"):
            headings.append(tag.get_text(" ", strip=True))
    except Exception:
        headings = re.findall(r"<h[45][^>]*>(.*?)</h[45]>", html_text, flags=re.IGNORECASE | re.DOTALL)
        headings = [re.sub(r"<[^>]+>", "", h).strip() for h in headings]

    meetings: list[FomcMeeting] = []
    for h in headings:
        meeting = build_meeting_from_heading(h)
        if meeting:
            meetings.append(meeting)

    meetings = sorted({m.meeting_id: m for m in meetings}.values(), key=lambda x: x.end_date)
    return meetings


def parse_fomc_meetings_from_html(html_text: str, *, source_url: str = FED_CALENDAR_URL) -> List[FomcMeeting]:
    """
    Parse meeting date ranges from the official Fed calendar page.

    Convention: Meeting "date" is the end date (statement release day),
    while we also retain the start date for completeness.
    """

    def build_meeting(*, year: int, month_name: str, date_text: str) -> Optional[FomcMeeting]:
        month_num = MONTHS.get((month_name or "").lower())
        if not month_num:
            return None
        cleaned = _normalize_dash(date_text or "")
        cleaned = re.sub(r"[^0-9\\-]", "", cleaned)
        if not cleaned:
            return None

        if "-" in cleaned:
            left, right = (part.strip() for part in cleaned.split("-", 1))
            start_day = _safe_int(left)
            end_day = _safe_int(right)
        else:
            start_day = _safe_int(cleaned.strip())
            end_day = start_day

        if not start_day or not end_day:
            return None

        start_dt = date(year, month_num, start_day)
        end_year = year
        end_month = month_num
        if end_day < start_day:
            if month_num == 12:
                end_year = year + 1
                end_month = 1
            else:
                end_month = month_num + 1
        end_dt = date(end_year, end_month, end_day)

        meeting_id = end_dt.isoformat()
        label = _compute_label(year, month_name, start_day, end_year, end_month, end_day)
        return FomcMeeting(
            meeting_id=meeting_id,
            start_date=start_dt,
            end_date=end_dt,
            year=year,
            label=label,
            source_url=source_url,
        )

    meetings: List[FomcMeeting] = []

    # Prefer robust HTML parsing via BeautifulSoup (already in requirements).
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.select("div.panel-heading h4 a"):
            title = (a.get_text(" ", strip=True) or "").strip()
            m = re.search(r"\b(20\d{2})\s+FOMC\s+Meetings\b", title, flags=re.IGNORECASE)
            if not m:
                continue
            year = int(m.group(1))
            panel_heading = a.find_parent("div", class_=re.compile(r"panel-heading", re.IGNORECASE))
            panel = panel_heading.find_parent("div", class_=re.compile(r"panel", re.IGNORECASE)) if panel_heading else None
            if not panel:
                continue

            for row in panel.select("div.fomc-meeting"):
                month_el = row.select_one(".fomc-meeting__month")
                date_el = row.select_one(".fomc-meeting__date")
                month_name = (month_el.get_text(" ", strip=True) if month_el else "") or ""
                month_name = month_name.replace("\xa0", " ").strip()
                # Month element might contain extra text; keep the first word (e.g., "January")
                month_name = (month_name.split() or [""])[0]
                date_text = (date_el.get_text(" ", strip=True) if date_el else "") or ""
                meeting = build_meeting(year=year, month_name=month_name, date_text=date_text)
                if meeting:
                    meetings.append(meeting)
    except Exception:
        # Regex fallback (best-effort)
        year_section_re = re.compile(r"(?P<year>20\d{2})\s+FOMC\s+Meetings", flags=re.IGNORECASE)
        row_re = re.compile(
            r"fomc-meeting__month[^>]*>\s*<strong>(?P<month>[A-Za-z]+)</strong>.*?"
            r"fomc-meeting__date[^>]*>(?P<dates>.*?)</div>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        matches = list(year_section_re.finditer(html_text))
        for idx, m in enumerate(matches):
            year = int(m.group("year"))
            start = m.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(html_text)
            section = html_text[start:end]
            for row in row_re.finditer(section):
                month_name = (row.group("month") or "").strip()
                date_html = row.group("dates") or ""
                date_text = re.sub(r"<[^>]+>", "", date_html)
                meeting = build_meeting(year=year, month_name=month_name, date_text=date_text)
                if meeting:
                    meetings.append(meeting)

    meetings = sorted({m.meeting_id: m for m in meetings}.values(), key=lambda x: x.end_date)
    return meetings


def _calendar_cache_path(*, start: date, end: date) -> Path:
    MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
    return MEETINGS_DIR / f"fomc_calendar_{start.isoformat()}_{end.isoformat()}.json"


def load_cached_calendar(*, start: date, end: date) -> Optional[List[FomcMeeting]]:
    path = _calendar_cache_path(start=start, end=end)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    meetings = [FomcMeeting.from_dict(x) for x in (payload.get("meetings") or [])]
    return meetings


def save_calendar_cache(*, start: date, end: date, meetings: Iterable[FomcMeeting], source_url: str) -> Path:
    path = _calendar_cache_path(start=start, end=end)
    payload = {
        "source_url": source_url,
        "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "meetings": [m.to_dict() for m in meetings],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def ensure_fomc_calendar(
    *,
    start: date,
    end: date,
    force_refresh: bool = False,
    url: str = FED_CALENDAR_URL,
) -> List[FomcMeeting]:
    cached = None if force_refresh else load_cached_calendar(start=start, end=end)
    if cached and len(cached) > 0:
        # Guard against older caches created when parsing logic was incomplete.
        years = {m.end_date.year for m in cached}
        expected_years = set(range(start.year, end.year + 1))
        missing = sorted(y for y in expected_years if y not in years)
        # If we're missing a meaningful block (e.g., 2011-2019), refresh.
        if len(missing) <= 2:
            return [m for m in cached if m.end_date >= start and m.end_date <= end]

    all_meetings: list[FomcMeeting] = []

    # 2020+ meetings are available on the main calendars page.
    html_text = fetch_fomc_calendar_html(url=url)
    all_meetings.extend(parse_fomc_meetings_from_html(html_text, source_url=url))

    # 2010-2019 meetings live on per-year historical pages.
    for y in range(max(2010, start.year), min(2019, end.year) + 1):
        hist_url = FED_HISTORICAL_YEAR_URL.format(year=y)
        hist_html = fetch_fomc_historical_year_html(year=y)
        all_meetings.extend(parse_fomc_historical_year_meetings_from_html(hist_html, year=y, source_url=hist_url))

    meetings = [m for m in all_meetings if m.end_date >= start and m.end_date <= end]
    meetings = sorted({m.meeting_id: m for m in meetings}.values(), key=lambda x: x.end_date)
    save_calendar_cache(start=start, end=end, meetings=meetings, source_url=url)
    return meetings
