from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from fomc.config import load_env
from .backend import (
    PortalError,
    export_cpi_pdf,
    export_macro_pdf,
    export_labor_pdf,
    list_macro_months,
    refresh_macro_month,
    get_macro_month,
    fetch_indicator_data,
    generate_cpi_report,
    generate_labor_report,
    get_db_job,
    get_indicator_health,
    list_indicator_tree,
    start_refresh_indicator_job,
    start_sync_indicators_job,
)
from fomc.data.database.connection import SessionLocal
from fomc.data.modeling.taylor_service import build_taylor_series_from_db
from fomc.rules.taylor_rule import ModelType

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


@app.get("/toolbox", response_class=HTMLResponse)
def toolbox_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        "toolbox.html",
        {"request": request, "default_month": _default_month()},
    )


@app.get("/reports")
def redirect_reports():
    return RedirectResponse(url="/toolbox", status_code=307)


@app.get("/macro-events")
def redirect_macro_events():
    return RedirectResponse(url="/toolbox", status_code=307)


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


@app.get("/api/macro-events/months")
def api_macro_months(order: str = Query("desc")):
    try:
        return list_macro_months(order=order)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/macro-events/refresh")
def api_macro_refresh(month: str = Query(..., regex=r"^\d{4}-\d{2}$")):
    try:
        return refresh_macro_month(month)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/macro-events/pdf")
def api_macro_pdf(
    month: str = Query(..., regex=r"^\d{4}-\d{2}$"),
    refresh: bool = False,
):
    try:
        pdf_bytes, headers = export_macro_pdf(month, refresh=refresh)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": headers.get("Content-Disposition", f'attachment; filename="macro_{month}.pdf"')},
        )
    except PortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/reports/labor.pdf")
def api_labor_pdf(month: str = Query(..., regex=r"^\d{4}-\d{2}$")):
    try:
        pdf_bytes, headers = export_labor_pdf(month)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": headers.get("Content-Disposition", f'attachment; filename="labor_{month}.pdf"')
            },
        )
    except PortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/reports/cpi.pdf")
def api_cpi_pdf(month: str = Query(..., regex=r"^\d{4}-\d{2}$")):
    try:
        pdf_bytes, headers = export_cpi_pdf(month)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": headers.get("Content-Disposition", f'attachment; filename="cpi_{month}.pdf"')
            },
        )
    except PortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/indicators")
def api_indicators():
    try:
        return list_indicator_tree()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/indicator-data")
def api_indicator_data(
    indicator_id: int = Query(..., ge=1),
    date_range: str = Query("3Y"),
):
    try:
        return fetch_indicator_data(indicator_id, date_range=date_range)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class SyncIndicatorsPayload(BaseModel):
    start_date: str | None = Field(default=None, description="YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD")
    requests_per_minute: int = 30
    default_start_date: str = "2010-01-01"
    full_refresh: bool = False


class RefreshIndicatorPayload(BaseModel):
    indicator_id: int
    start_date: str | None = Field(default=None, description="YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD")
    requests_per_minute: int = 30
    default_start_date: str = "2010-01-01"
    full_refresh: bool = False


@app.post("/api/db/jobs/sync-indicators")
def api_db_sync(payload: SyncIndicatorsPayload):
    try:
        return start_sync_indicators_job(
            start_date=payload.start_date,
            end_date=payload.end_date,
            requests_per_minute=payload.requests_per_minute,
            default_start_date=payload.default_start_date,
            full_refresh=payload.full_refresh,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/db/jobs/refresh-indicator")
def api_db_refresh(payload: RefreshIndicatorPayload):
    try:
        return start_refresh_indicator_job(
            indicator_id=payload.indicator_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            requests_per_minute=payload.requests_per_minute,
            default_start_date=payload.default_start_date,
            full_refresh=payload.full_refresh,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/db/jobs/{job_id}")
def api_db_job(job_id: str):
    job = get_db_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/db/indicator-health")
def api_db_indicator_health(indicator_id: int = Query(..., ge=1)):
    try:
        return get_indicator_health(indicator_id)
    except PortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class TaylorModelPayload(BaseModel):
    model: ModelType = ModelType.TAYLOR
    start_date: str | None = Field(default=None, description="YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD")
    real_rate: float | None = None
    target_inflation: float | None = None
    alpha: float | None = None
    beta: float | None = None
    okun: float | None = None
    intercept: float | None = None
    rho: float | None = None

    inflation_code: str = "PCEPILFE"
    unemployment_code: str = "UNRATE"
    nairu_code: str = "NROU"
    fed_effective_code: str = "EFFR"


@app.post("/api/models/taylor")
def api_models_taylor(payload: TaylorModelPayload):
    session = SessionLocal()
    try:
        return build_taylor_series_from_db(
            session=session,
            model=payload.model,
            start_date=payload.start_date,
            end_date=payload.end_date,
            real_rate=payload.real_rate,
            target_inflation=payload.target_inflation,
            alpha=payload.alpha,
            beta=payload.beta,
            okun=payload.okun,
            intercept=payload.intercept,
            rho=payload.rho,
            inflation_code=payload.inflation_code,
            unemployment_code=payload.unemployment_code,
            nairu_code=payload.nairu_code,
            fed_effective_code=payload.fed_effective_code,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        session.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fomc.apps.web.main:app", host="0.0.0.0", port=9000, reload=True)
