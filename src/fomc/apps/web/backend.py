"""
Integration layer that stitches together the existing report generator (Flask)
and the macro-events pipeline so the portal can expose them behind one API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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

load_env()


class PortalError(RuntimeError):
    """Raised when an underlying app returns a failure."""


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
