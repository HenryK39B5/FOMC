"""Minimal FastAPI app to browse the macro events SQLite database."""

from __future__ import annotations

from typing import List
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import markdown2

from macro_events import DEFAULT_DB_PATH
from macro_events.config import REPORT_TYPES
from macro_events.db import get_connection, get_events_for_month
from macro_events.month_service import ensure_month_events

app = FastAPI(title="Macro Events Browser")


def _list_months():
    conn = get_connection(DEFAULT_DB_PATH)
    cur = conn.execute("SELECT * FROM months ORDER BY month_key DESC, report_type ASC;")
    months = [dict(row) for row in cur.fetchall()]
    conn.close()
    return months


def _render_html_page(body: str) -> HTMLResponse:
    template = f"""
    <html>
        <head>
            <title>Macro Events DB</title>
            <style>
                :root {{
                    --bg: #f8fafc;
                    --card: #ffffff;
                    --text: #0f172a;
                    --muted: #475569;
                    --accent: #2563eb;
                    --border: #e2e8f0;
                }}
                body {{
                    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
                    color: var(--text);
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 24px;
                }}
                h2, h3 {{
                    margin-bottom: 12px;
                }}
                .grid {{
                    display: grid;
                    grid-template-columns: 1fr;
                    gap: 16px;
                    align-items: start;
                }}
                .events-card {{
                    position: relative;
                    border-radius: 24px;
                    padding: 20px 22px 22px;
                    border: 1px solid rgba(148, 163, 184, 0.35);
                    background: linear-gradient(135deg, rgba(255, 255, 255, 0.85), rgba(248, 250, 252, 0.95));
                    box-shadow: 0 24px 60px rgba(15, 23, 42, 0.14), 0 0 0 1px rgba(255, 255, 255, 0.7);
                    backdrop-filter: blur(18px);
                }}
                .events-header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 12px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid rgba(226, 232, 240, 0.8);
                }}
                .events-header h3 {{
                    margin: 0;
                    font-size: 20px;
                    letter-spacing: 0.02em;
                }}
                .events-header .muted {{
                    margin-top: 4px;
                    font-size: 13px;
                }}
                .events-timeline {{
                    position: relative;
                    margin-top: 16px;
                    padding-left: 18px;
                    display: flex;
                    flex-direction: column;
                    gap: 14px;
                }}
                .events-timeline::before {{
                    content: "";
                    position: absolute;
                    top: 4px;
                    bottom: 4px;
                    left: 6px;
                    width: 2px;
                    background: linear-gradient(to bottom, #bfdbfe, #e2e8f0);
                    opacity: 0.9;
                }}
                .event-item {{
                    position: relative;
                    border-radius: 18px;
                    padding: 12px 14px 12px 16px;
                    background: radial-gradient(circle at top left, #eff6ff 0%, #ffffff 55%);
                    border: 1px solid rgba(203, 213, 225, 0.9);
                    box-shadow: 0 14px 32px rgba(15, 23, 42, 0.08);
                    transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
                }}
                .event-item::before {{
                    content: "";
                    position: absolute;
                    left: -12px;
                    top: 18px;
                    width: 10px;
                    height: 10px;
                    border-radius: 999px;
                    border: 2px solid #ffffff;
                    background: linear-gradient(135deg, #2563eb, #4f46e5);
                    box-shadow: 0 0 0 4px rgba(191, 219, 254, 0.8);
                }}
                .event-item:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 20px 40px rgba(15, 23, 42, 0.12);
                    border-color: rgba(129, 140, 248, 0.9);
                }}
                .event-header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    gap: 8px;
                }}
                .event-meta {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 6px;
                    font-size: 12px;
                }}
                .event-meta .event-date {{
                    padding: 2px 8px;
                    border-radius: 999px;
                    background: rgba(15, 23, 42, 0.06);
                    color: #0f172a;
                }}
                .event-meta .tag {{
                    padding: 2px 8px;
                    border-radius: 999px;
                    border: 1px solid rgba(148, 163, 184, 0.5);
                    background: rgba(255, 255, 255, 0.75);
                }}
                .tag-supply_chain {{ background: #e0f2fe; border-color: #bae6fd; color: #0369a1; }}
                .tag-trade_tariff {{ background: #fef3c7; border-color: #fde68a; color: #92400e; }}
                .tag-sanctions {{ background: #fee2e2; border-color: #fecaca; color: #b91c1c; }}
                .tag-other {{ background: #ede9fe; border-color: #ddd6fe; color: #5b21b6; }}
                .event-channels {{
                    padding: 2px 8px;
                    border-radius: 999px;
                    background: rgba(226, 232, 240, 0.6);
                    color: #475569;
                }}
                .event-score {{
                    display: inline-flex;
                    flex-direction: column;
                    align-items: flex-end;
                    font-size: 11px;
                    line-height: 1.2;
                    padding: 4px 8px;
                    border-radius: 999px;
                    background: rgba(15, 23, 42, 0.88);
                    color: #e5e7eb;
                    min-width: 64px;
                }}
                .event-score-label {{ opacity: 0.7; }}
                .event-score-value {{ font-size: 15px; font-weight: 600; }}
                .event-title {{
                    margin: 8px 0 4px;
                    font-size: 16px;
                    font-weight: 600;
                    line-height: 1.5;
                    letter-spacing: 0.01em;
                }}
                .event-summary {{
                    font-size: 14px;
                    line-height: 1.8;
                    color: #0f172a;
                    margin: 2px 0 6px;
                }}
                .event-footer {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-top: 4px;
                }}
                .event-sources-count {{
                    font-size: 12px;
                    color: #6b7280;
                }}
                .event-sources {{
                    margin-top: 6px;
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                    gap: 8px;
                }}
                .sources-wrap {{
                    background: #f8fafc;
                    border: 1px solid var(--border);
                    border-radius: 10px;
                    padding: 10px;
                    max-height: 420px;
                    overflow-y: auto;
                }}
                .summary-card {{
                    max-width: 800px;
                    margin: 24px auto 80px;
                    background: linear-gradient(145deg, #ffffff 0%, #eef2ff 100%);
                    border: 1px solid var(--border);
                    border-radius: 18px;
                    padding: 24px 28px;
                    box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
                    line-height: 1.6;
                }}
                .summary-card h4 {{ margin-top: 0; }}
                .summary-card h5 {{ margin-bottom: 4px; }}
                .markdown p {{ margin: 6px 0; }}
                .markdown strong {{ color: #0f172a; }}
                .markdown ul {{ padding-left: 20px; }}
                .markdown li {{ margin: 4px 0; }}
                .summary-card.markdown h2 {{ margin: 18px 0 10px; }}
                .summary-card.markdown p {{ margin: 8px 0; font-size: 15px; line-height: 1.8; }}
                .summary-meta {{
                    font-size: 13px;
                    color: var(--muted);
                    margin-bottom: 6px;
                }}
                .source-group {{
                    display: flex;
                    flex-wrap: wrap;
                    align-items: center;
                    gap: 8px;
                    margin-top: 8px;
                    padding-top: 4px;
                    border-top: 1px dashed var(--border);
                }}
                .source-label {{
                    font-size: 13px;
                    color: var(--muted);
                }}
                .source-chip {{
                    display: inline-flex;
                    align-items: center;
                    padding: 4px 10px;
                    border-radius: 999px;
                    background: #e5edff;
                    font-size: 13px;
                    color: #1d4ed8;
                    text-decoration: none;
                    border: 1px solid rgba(129, 140, 248, 0.6);
                    transition: background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
                }}
                .source-chip:hover {{
                    background: #dbe3ff;
                    transform: translateY(-1px);
                    box-shadow: 0 8px 20px rgba(129, 140, 248, 0.3);
                }}
                .tag {{
                    display: inline-block;
                    padding: 2px 8px;
                    border-radius: 12px;
                    background: #e0e7ff;
                    color: #4338ca;
                    font-size: 12px;
                    margin-right: 6px;
                }}
                .summary-button {{
                    padding: 4px 10px;
                    border-radius: 999px;
                    background: var(--accent);
                    color: #fff;
                    font-size: 13px;
                    border: none;
                    cursor: pointer;
                    text-decoration: none;
                }}
                .summary-button:hover {{ opacity: 0.9; }}
                .chip {{
                    display: inline-block;
                    padding: 4px 8px;
                    border-radius: 10px;
                    font-size: 12px;
                    margin: 2px;
                    color: #0f172a;
                    background: #e2e8f0;
                }}
                .chip.primary {{ background: #dbeafe; color: #1d4ed8; font-weight: 600; }}
                .chip.supp {{ background: #f1f5f9; color: #475569; }}
                .source-box {{
                    background: rgba(248, 250, 252, 0.9);
                    border: 1px solid rgba(148, 163, 184, 0.6);
                    border-radius: 14px;
                    padding: 8px 10px;
                    margin-bottom: 6px;
                    transition: transform 0.15s ease, box-shadow 0.15s ease;
                }}
                .source-box .title {{ font-weight: 600; margin-bottom: 4px; }}
                .source-box .excerpt {{ font-size: 13px; color: #334155; line-height: 1.5; }}
                .source-box a {{ color: var(--accent); text-decoration: none; }}
                .source-box:hover {{
                    transform: translateY(-1px);
                    box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12);
                }}
                .muted {{ color: var(--muted); font-size: 14px; }}
                @media (max-width: 640px) {{
                    .events-card {{ padding: 14px; }}
                    .event-item {{ padding: 10px 12px; }}
                    .event-title {{ font-size: 15px; }}
                    .events-header {{ flex-direction: column; align-items: flex-start; gap: 8px; }}
                    .events-timeline {{ padding-left: 14px; }}
                    .event-header {{ flex-direction: column; align-items: flex-start; gap: 4px; }}
                    .event-score {{ align-self: flex-start; }}
                    .event-sources {{ grid-template-columns: 1fr; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Macro Events Database</h2>
                <div class="muted">统一宏观抓取 + LLM 筛选/摘要 + 月报</div>
                <div style="margin-top:12px;">
                    <form action="/ui/fetch" method="get">
                        <label>Month (YYYY-MM):
                            <input name="month_key" required placeholder="2024-08" style="padding:6px 8px;"/>
                        </label>
                        <input type="hidden" name="report_type" value="macro" />
                        <label style="margin-left:8px;"><input type="checkbox" name="force_refresh" value="1"> Force refresh</label>
                        <button type="submit" style="margin-left:8px;padding:6px 12px;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;">Fetch/Refresh</button>
                    </form>
                </div>
                {body}
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=template)


@app.get("/", response_class=HTMLResponse)
def home():
    months = _list_months()
    if not months:
        body = "<p>No months in database yet. Use the form above to fetch data.</p>"
    else:
        body_rows_parts = []
        for m in months:
            summary_link = "—"
            if m.get("monthly_summary"):
                summary_link = f"<a href='/ui/summary/{m['month_key']}/{m['report_type']}'>View summary</a>"
            body_rows_parts.append(
                f"<tr><td>{m['month_key']}</td>"
            f"<td>{m['report_type']}</td>"
                f"<td>{m['status']}</td>"
                f"<td>{m.get('num_events', 0)}</td>"
                f"<td><a href='/ui/month/{m['month_key']}/{m['report_type']}'>View events</a></td>"
                f"<td>{summary_link}</td></tr>"
            )
        body_rows = "".join(body_rows_parts)
        body = f"""
        <h3>Cached months</h3>
        <table>
            <tr><th>Month</th><th>Report Type</th><th>Status</th><th>Events</th><th>Events</th><th>Monthly Summary</th></tr>
            {body_rows}
        </table>
        """
    return _render_html_page(body)


@app.get("/ui/month/{month_key}/{report_type}", response_class=HTMLResponse)
def ui_month(month_key: str, report_type: str):
    if report_type not in REPORT_TYPES:
        report_type = "macro"
    conn = get_connection(DEFAULT_DB_PATH)
    events = get_events_for_month(conn, month_key, report_type)
    # raw articles map
    raw_map = {}
    urls = [u for ev in events for u in (ev.get("source_urls") or [])]
    if urls:
        cur = conn.execute(
            "SELECT url, title, full_text, snippet, source_domain FROM raw_articles WHERE url IN (SELECT value FROM json_each(?))",
            (json.dumps(urls),),
        )
        for row in cur.fetchall():
            raw_map[row["url"]] = dict(row)
    conn.close()
    if not events:
        body = f"<p>No events stored for {month_key} / {report_type}. Try fetch above.</p>"
        return _render_html_page(body)

    event_items = []
    for ev in events:
        source_meta = ev.get("source_meta") or []
        source_boxes = ""
        primary_count = 0
        supp_count = 0
        if source_meta and isinstance(source_meta, list):
            for s in source_meta:
                url = s.get("url")
                article = raw_map.get(url)
                content = ""
                if s.get("important"):
                    primary_count += 1
                    content = (article.get("full_text") or "") if article else ""
                else:
                    supp_count += 1
                    content = (article.get("snippet") or "") if article else ""
                if not content and article:
                    content = article.get("snippet") or ""
                if content and len(content) > 600:
                    content = content[:600] + "..."
                excerpt_html = markdown2.markdown(content) if content else ""
                chip_class = "primary" if s.get("important") else "supp"
                chip_label = "PRIMARY" if s.get("important") else "SUPP"
                source_boxes += (
                    f"<div class='source-box'>"
                    f"<div class='chip {chip_class}'>{chip_label}</div>"
                    f"<div class='title'><a href='{url}' target='_blank'>{s.get('title') or url}</a></div>"
                    f"<div class='muted'>{s.get('domain','')}</div>"
                    f"<div class='excerpt markdown'>{excerpt_html}</div>"
                    f"</div>"
                )
        event_items.append(
            f"<article class='event-item'>"
            f"<header class='event-header'>"
            f"<div class='event-meta'>"
            f"<span class='event-date'>{ev.get('date','')}</span>"
            f"<span class='tag tag-{ev.get('macro_shock_type','')}'>{ev.get('macro_shock_type','')}</span>"
            f"<span class='event-channels'>{', '.join(ev.get('impact_channel', []) or [])}</span>"
            f"</div>"
            f"<span class='event-score'><span class='event-score-label'>Score</span><span class='event-score-value'>{ev.get('importance_score','')}</span></span>"
            f"</header>"
            f"<h4 class='event-title'>{ev.get('title','')}</h4>"
            f"<p class='event-summary'>{ev.get('summary_zh','')}</p>"
            f"<div class='event-footer'>"
            f"<span class='event-sources-count'>{primary_count} primary · {supp_count} supplementary</span>"
            f"</div>"
            f"<div class='event-sources'>{source_boxes or ''}</div>"
            f"</article>"
        )
    events_column = (
        f"<div class='events-card'>"
        f"<div class='events-header'>"
        f"<div><h3 style='margin:0;'>Events for {month_key} / {report_type}</h3><p class='muted'>LLM summarization applied per event</p></div>"
        f"<a class='summary-button' href='/ui/summary/{month_key}/{report_type}'>Monthly report</a>"
        f"</div>"
        f"<div class='events-timeline'>{''.join(event_items)}</div>"
        f"</div>"
    )
    table = f"""
    <div class="grid">
        {events_column}
    </div>
    """
    return _render_html_page(table)


@app.get("/months")
def list_months():
    return _list_months()


@app.get("/events")
def list_events(
    month_key: str = Query(..., description="YYYY-MM"),
    report_type: str = Query("macro", description="report type (ignored; default macro)"),
    fetch_if_missing: bool = Query(False, description="If true, trigger fetch when missing"),
    force_refresh: bool = Query(False, description="If true, bypass cache"),
    use_llm: bool = Query(True, description="LLM is always used; kept for compatibility"),
    llm_model: str | None = Query(None, description="Optional LLM model override"),
):
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid report_type")
    if fetch_if_missing or force_refresh or use_llm:
        events = ensure_month_events(
            month_key,
            report_type,
            force_refresh=force_refresh,
            use_llm=True,
            llm_model=llm_model,
            db_path=DEFAULT_DB_PATH,
        )
    else:
        conn = get_connection(DEFAULT_DB_PATH)
        events = get_events_for_month(conn, month_key, report_type)
        conn.close()
        if not events:
            raise HTTPException(status_code=404, detail="No events cached for this month")
    return events


@app.get("/ui/fetch", response_class=HTMLResponse)
def ui_fetch(
    month_key: str,
    report_type: str = "macro",
    force_refresh: int | None = Query(default=None, description="1 to force refresh"),
):
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid report_type")
    events = ensure_month_events(
        month_key,
        report_type,
        force_refresh=bool(force_refresh),
        use_llm=True,
        db_path=DEFAULT_DB_PATH,
    )
    rows = "".join(
        f"<tr><td>{ev.get('date','')}</td><td>{ev.get('macro_shock_type','')}</td>"
        f"<td>{', '.join(ev.get('impact_channel', []) or [])}</td>"
        f"<td>{ev.get('importance_score','')}</td>"
        f"<td>{ev.get('summary_zh','')}</td></tr>"
        for ev in events
    )
    table = f"""
    <h3>Fetched {len(events)} events for {month_key} / {report_type}</h3>
    <p><a href='/ui/summary/{month_key}/{report_type}'>View monthly summary</a></p>
    <table>
        <tr><th>Date</th><th>Shock Type</th><th>Impact</th><th>Score</th><th>Summary</th></tr>
        {rows}
    </table>
    <p><a href='/ui/month/{month_key}/{report_type}'>View with sources</a></p>
    """
    return _render_html_page(table)


@app.get("/ui/summary/{month_key}/{report_type}", response_class=HTMLResponse)
def ui_summary(month_key: str, report_type: str):
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid report_type")
    conn = get_connection(DEFAULT_DB_PATH)
    cur = conn.execute(
        "SELECT monthly_summary FROM months WHERE month_key = ? AND report_type = ?",
        (month_key, report_type),
    )
    row = cur.fetchone()
    conn.close()
    summary = row["monthly_summary"] if row else None
    if not summary:
        body = f"<p>No monthly summary found for {month_key} / {report_type}.</p>"
    else:
        summary_html = markdown2.markdown(summary)
        # JS to transform '来源' lines into source chips
        script = """
        <script>
        document.addEventListener('DOMContentLoaded', function() {
            const blocks = document.querySelectorAll('.summary-card.markdown p');
            blocks.forEach(p => {
                const text = p.innerText.trim();
                if (text.startsWith('来源') || text.startsWith('来源:') || text.startsWith('来源：')) {
                    const urls = text.replace(/^来源[:：]?\\s*/, '').split(/\\s+/).filter(Boolean);
                    const group = document.createElement('div');
                    group.className = 'source-group';
                    const label = document.createElement('span');
                    label.className = 'source-label';
                    label.textContent = '📎 来源';
                    group.appendChild(label);
                    urls.forEach(u => {
                        const a = document.createElement('a');
                        a.className = 'source-chip';
                        a.href = u;
                        a.target = '_blank';
                        a.rel = 'noreferrer';
                        try {{ a.textContent = new URL(u).hostname.replace(/^www\\./,''); }} catch (e) {{ a.textContent = u; }}
                        group.appendChild(a);
                    });
                    p.replaceWith(group);
                }
            });
        });
        </script>
        """
        body = (
            f"<div class='summary-card markdown'>"
            f"<div class='summary-meta'>自动抓取宏观事件 + LLM 汇总</div>"
            f"<h3>Monthly Summary for {month_key} / {report_type}</h3>"
            f"{summary_html}"
            f"</div>"
            f"{script}"
        )
    return _render_html_page(body)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
