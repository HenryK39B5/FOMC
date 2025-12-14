from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from fomc.data.modeling.taylor_inputs import (
    compute_output_gap,
    load_indicator_series_by_code,
    monthly_ffill,
)
from fomc.data.database.models import EconomicIndicator
from fomc.rules.taylor_rule import (
    ModelType,
    RatePoint,
    TaylorRuleParams,
    calculate_adjusted_rate,
    calculate_rate,
    latest_metrics,
    model_defaults,
)


def _to_monthly(df: pd.DataFrame, *, method: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.set_index("date").sort_index()
    if method == "mean":
        out = out.resample("M").mean()
    elif method == "last":
        out = out.resample("M").last()
    else:
        raise ValueError(f"Unsupported resample method: {method}")
    out = out.reset_index()
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["value"])
    return out[["date", "value"]]


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _default_date_window(end: datetime) -> Tuple[datetime, datetime]:
    start = end.replace(year=end.year - 10)
    return start, end


def _compute_yoy_percent_from_index(monthly_df: pd.DataFrame) -> pd.DataFrame:
    if monthly_df.empty:
        return monthly_df.copy()
    out = monthly_df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["value"] = out["value"].pct_change(12) * 100.0
    out = out.dropna(subset=["value"])
    return out.reset_index(drop=True)[["date", "value"]]


def _infer_inflation_is_index(session: Session, code: str, series: pd.DataFrame) -> bool:
    """
    Decide whether an inflation series is an index level that needs YoY conversion.
    - If indicator units mention 'Index' -> treat as index.
    - If units mention percent/% -> treat as already a rate.
    - Fallback heuristic: if median level is large (e.g., 50~500) treat as index.
    """
    try:
        meta = session.query(EconomicIndicator.units).filter(EconomicIndicator.code == code).first()
        units = (meta[0] if meta else "") or ""
    except Exception:
        units = ""

    units_l = units.lower()
    if "index" in units_l:
        return True
    if "percent" in units_l or "%" in units:
        return False

    if series.empty:
        return False
    vals = pd.to_numeric(series.get("value"), errors="coerce").dropna()
    if vals.empty:
        return False
    med = float(vals.median())
    return med >= 20.0


def build_taylor_series_from_db(
    *,
    session: Session,
    model: ModelType,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    real_rate: Optional[float] = None,
    target_inflation: Optional[float] = None,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    okun: Optional[float] = None,
    intercept: Optional[float] = None,
    rho: Optional[float] = None,
    inflation_code: str = "PCEPILFE",
    unemployment_code: str = "UNRATE",
    nairu_code: str = "NROU",
    fed_effective_code: str = "EFFR",
) -> Dict[str, Any]:
    """
    Compute a Taylor-rule series from real DB data.

    Data sources (defaults):
    - core inflation: PCEPILFE (core PCE YoY, monthly)
    - unemployment: UNRATE (monthly)
    - NAIRU: NROU (CBO estimate, quarterly/annual-ish; forward-filled to monthly)
    - fed rate: EFFR (daily; monthly mean)
    - output gap: computed from GDPC1 & GDPPOT and forward-filled to monthly
    """
    now = datetime.utcnow()
    requested_end = _parse_date(end_date) if end_date else now
    requested_start = _parse_date(start_date) if start_date else None

    end = requested_end
    start = requested_start if requested_start else _default_date_window(end)[0]

    def _load_core_series(window_start: datetime, window_end: datetime) -> tuple[pd.DataFrame, str, pd.DataFrame]:
        """
        Load core inputs (inflation + unemployment) for a window.

        If inflation is an index series, we compute YoY via pct_change(12), which requires
        ~12 months of lookback; we therefore fetch inflation with lookback and then filter
        back to [window_start, window_end].
        """

        inflation_start = window_start
        # Extra lookback to ensure YoY has enough history even for short windows (e.g., 1Y).
        inflation_lookback = timedelta(days=400)
        inflation_fetch_start = window_start - inflation_lookback

        inflation_raw = load_indicator_series_by_code(inflation_code, session, start=inflation_fetch_start, end=window_end)
        inflation_m_local = monthly_ffill(inflation_raw)
        inflation_transform_local = "raw"
        if _infer_inflation_is_index(session, inflation_code, inflation_m_local):
            inflation_m_local = _compute_yoy_percent_from_index(inflation_m_local)
            inflation_transform_local = "yoy"

        if not inflation_m_local.empty:
            inflation_m_local["date"] = pd.to_datetime(inflation_m_local["date"])
            inflation_m_local = inflation_m_local[
                (inflation_m_local["date"] >= pd.Timestamp(inflation_start))
                & (inflation_m_local["date"] <= pd.Timestamp(window_end))
            ].reset_index(drop=True)

        unemployment_raw = load_indicator_series_by_code(unemployment_code, session, start=window_start, end=window_end)
        unemployment_m_local = monthly_ffill(unemployment_raw)
        return inflation_m_local, inflation_transform_local, unemployment_m_local

    inflation_m, inflation_transform, unemployment_m = _load_core_series(start, end)

    # Clamp end_date to the latest common month for core inputs (inflation + unemployment).
    # This avoids empty windows when the requested end_date is beyond DB coverage (e.g., future meetings).
    try:
        infl_max = pd.to_datetime(inflation_m["date"]).max() if not inflation_m.empty else None
        unemp_max = pd.to_datetime(unemployment_m["date"]).max() if not unemployment_m.empty else None
        common_end = None
        if infl_max is not None and unemp_max is not None and infl_max == infl_max and unemp_max == unemp_max:
            common_end = min(infl_max, unemp_max)
        if common_end is not None:
            common_end_dt = pd.Timestamp(common_end).to_pydatetime()
            if end > common_end_dt:
                # Preserve requested window length when both bounds were provided.
                if requested_start is not None and end_date is not None:
                    delta = end - requested_start
                    end = common_end_dt
                    start = end - delta
                else:
                    end = common_end_dt
                    if requested_start is None:
                        start = _default_date_window(end)[0]

                # Reload core series with the adjusted window.
                inflation_m, inflation_transform, unemployment_m = _load_core_series(start, end)
    except Exception:
        # Best-effort; never fail the whole API due to clamping logic.
        pass

    nairu = load_indicator_series_by_code(nairu_code, session, start=start, end=end)
    nairu_m = monthly_ffill(nairu)

    fed = load_indicator_series_by_code(fed_effective_code, session, start=start, end=end)
    fed_m = _to_monthly(fed, method="mean")

    gap_m = compute_output_gap(session, start=start, end=end)

    def to_key(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["month", col_name])
        out = df.copy()
        out["month"] = pd.to_datetime(out["date"]).dt.to_period("M").astype(str)
        out[col_name] = pd.to_numeric(out["value"], errors="coerce")
        out = out.dropna(subset=[col_name])
        return out[["month", col_name]].drop_duplicates(subset=["month"], keep="last")

    merged = (
        to_key(inflation_m, "inflation")
        .merge(to_key(unemployment_m, "unemployment"), on="month", how="inner")
        .merge(to_key(nairu_m, "nairu"), on="month", how="left")
        .merge(to_key(gap_m, "output_gap"), on="month", how="left")
        .merge(to_key(fed_m, "fed"), on="month", how="left")
    )

    if merged.empty:
        return {
            "series": [],
            "metrics": latest_metrics(model_defaults(model), []),
            "meta": {
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
                "inflation_code": inflation_code,
                "unemployment_code": unemployment_code,
                "nairu_code": nairu_code,
                "fed_effective_code": fed_effective_code,
            },
        }

    merged = merged.sort_values("month")
    merged["nairu"] = merged["nairu"].ffill()
    merged["output_gap"] = merged["output_gap"].fillna(0.0)
    merged["fed"] = merged["fed"].ffill()

    base = model_defaults(model)
    if real_rate is not None:
        base = replace(base, real_rate=float(real_rate))
    if target_inflation is not None:
        base = replace(base, target_inflation=float(target_inflation))
    if alpha is not None:
        base = replace(base, alpha=float(alpha))
    if beta is not None:
        base = replace(base, beta=float(beta))
    if okun is not None:
        base = replace(base, okun=float(okun))
    if intercept is not None:
        base = replace(base, intercept=float(intercept))
    if rho is not None:
        base = replace(base, rho=float(rho))

    points: List[RatePoint] = []
    prev_fed_rate = float(merged["fed"].iloc[0]) if merged["fed"].notna().any() else 0.0
    explain: Dict[str, Any] = {}

    for row in merged.itertuples(index=False):
        month = row.month
        dt = pd.Period(month, freq="M").end_time.date()
        fed_rate = float(row.fed) if row.fed == row.fed else prev_fed_rate
        params = replace(
            base,
            core_inflation=float(row.inflation),
            unemployment_rate=float(row.unemployment),
            nairu=float(row.nairu) if row.nairu == row.nairu else base.nairu,
            output_gap=float(row.output_gap) if row.output_gap == row.output_gap else 0.0,
            prev_fed_rate=float(prev_fed_rate),
        )
        taylor_rate = calculate_rate(params)
        adjusted_rate = calculate_adjusted_rate(taylor_rate, prev_fed_rate, params.rho)

        inflation_gap = float(params.core_inflation) - float(params.target_inflation)
        unemployment_gap = float(params.nairu) - float(params.unemployment_rate)
        term_inflation = float(params.core_inflation)
        term_infl_adj = float(params.alpha) * inflation_gap
        term_unemp_adj = float(params.beta) * float(params.okun) * unemployment_gap
        term_gap = float(params.output_gap)
        term_intercept = float(params.intercept)
        term_real = float(params.real_rate)

        explain = {
            "as_of": dt.isoformat(),
            "model": params.model.value,
            "inflation_transform": inflation_transform,
            "params": {
                "real_rate": float(params.real_rate),
                "target_inflation": float(params.target_inflation),
                "alpha": float(params.alpha),
                "beta": float(params.beta),
                "okun": float(params.okun),
                "intercept": float(params.intercept),
                "rho": float(params.rho),
            },
            "rule": {
                "symbolic": "i = r* + π + α(π-π*) + β·Okun·(u*-u) + y_gap + c",
                "numeric": (
                    f"i = {term_real:.2f} + {term_inflation:.2f} + "
                    f"{params.alpha:.2f}({params.core_inflation:.2f}-{params.target_inflation:.2f}) + "
                    f"{params.beta:.2f}·{params.okun:.2f}({params.nairu:.2f}-{params.unemployment_rate:.2f}) + "
                    f"{term_gap:.2f} + {term_intercept:.2f}"
                ),
                "terms": [
                    {"key": "real_rate", "label": "r*", "meaning": "中性实际利率", "value": float(params.real_rate), "editable": False},
                    {"key": "inflation", "label": "π", "meaning": f"{inflation_code} 通胀({inflation_transform})", "value": float(params.core_inflation), "editable": False},
                    {"key": "target_inflation", "label": "π*", "meaning": "通胀目标", "value": float(params.target_inflation), "editable": False},
                    {"key": "alpha", "label": "α", "meaning": "通胀缺口权重", "value": float(params.alpha), "editable": False},
                    {"key": "inflation_gap", "label": "(π-π*)", "meaning": "通胀缺口", "value": float(inflation_gap), "editable": False},
                    {"key": "unemployment", "label": "u", "meaning": f"{unemployment_code} 失业率", "value": float(params.unemployment_rate), "editable": False},
                    {"key": "nairu", "label": "u*", "meaning": f"{nairu_code} NAIRU", "value": float(params.nairu), "editable": False},
                    {"key": "beta", "label": "β", "meaning": "失业缺口权重", "value": float(params.beta), "editable": False},
                    {"key": "okun", "label": "Okun", "meaning": "Okun 系数", "value": float(params.okun), "editable": False},
                    {"key": "unemployment_gap", "label": "(u*-u)", "meaning": "失业缺口", "value": float(unemployment_gap), "editable": False},
                    {"key": "output_gap", "label": "y_gap", "meaning": "产出缺口", "value": float(params.output_gap), "editable": False},
                    {"key": "intercept", "label": "c", "meaning": "截距", "value": float(params.intercept), "editable": False},
                    {"key": "rho", "label": "ρ", "meaning": "政策惯性系数", "value": float(params.rho), "editable": True},
                ],
                "result": float(taylor_rate),
            },
            "smoothing": {
                "symbolic": "i_adj = ρ·i_prev + (1-ρ)·i",
                "numeric": f"i_adj = {params.rho:.2f}·{prev_fed_rate:.2f} + {(1-params.rho):.2f}·{taylor_rate:.2f}",
                "rho": float(params.rho),
                "prev_fed": float(prev_fed_rate),
                "result": float(adjusted_rate),
            },
            "inputs": {
                "inflation": float(params.core_inflation),
                "unemployment": float(params.unemployment_rate),
                "nairu": float(params.nairu),
                "output_gap": float(params.output_gap),
                "fed": float(fed_rate),
            },
        }

        points.append(
            RatePoint(
                date=dt,
                taylor=round(taylor_rate, 2),
                fed=round(fed_rate, 2),
                survey=round(float(params.survey_rate), 2),
                adjusted=round(adjusted_rate, 2),
                inflation=round(float(params.core_inflation), 2),
                unemployment=round(float(params.unemployment_rate), 2),
                nairu=round(float(params.nairu), 2),
                output_gap=round(float(params.output_gap), 2),
            )
        )
        prev_fed_rate = fed_rate

    return {
        "series": [p.as_dict() for p in points],
        "metrics": latest_metrics(base, points),
        "explain": explain,
        "meta": {
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "model": base.model.value,
            "inflation_transform": inflation_transform,
            "inflation_code": inflation_code,
            "unemployment_code": unemployment_code,
            "nairu_code": nairu_code,
            "fed_effective_code": fed_effective_code,
        },
    }
