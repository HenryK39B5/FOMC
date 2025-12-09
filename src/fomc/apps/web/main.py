from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from fomc.config import load_env
from .backend import PortalError, generate_cpi_report, generate_labor_report, get_macro_month

load_env()

APP_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="FOMC Portal", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def _default_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


@app.get("/", response_class=HTMLResponse)
def landing(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "default_month": _default_month(),
        },
    )


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        "reports.html",
        {"request": request, "default_month": _default_month()},
    )


@app.get("/macro-events", response_class=HTMLResponse)
def macro_events_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        "macro_events.html",
        {"request": request, "default_month": _default_month()},
    )


@app.get("/api/reports/labor")
def api_labor_report(month: str = Query(..., regex=r"^\d{4}-\d{2}$")):
    try:
        return generate_labor_report(month)
    except PortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/reports/cpi")
def api_cpi_report(month: str = Query(..., regex=r"^\d{4}-\d{2}$")):
    try:
        return generate_cpi_report(month)
    except PortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/macro-events")
def api_macro_events(
    month: str = Query(..., regex=r"^\d{4}-\d{2}$"),
    refresh: bool = False,
):
    try:
        return get_macro_month(month, refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.web.main:app", host="0.0.0.0", port=9000, reload=True)
