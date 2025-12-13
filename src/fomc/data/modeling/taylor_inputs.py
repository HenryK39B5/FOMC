from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from fomc.data.database.connection import SessionLocal
from fomc.data.database.models import EconomicDataPoint, EconomicIndicator


def load_indicator_series_by_code(
    code: str,
    session: Optional[Session] = None,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    Load a single indicator series from the main DB by FRED code.

    Returns a dataframe with columns: date (datetime64), value (float),
    sorted ascending by date. Empty dataframe if series missing.
    """
    owns_session = session is None
    if session is None:
        session = SessionLocal()

    try:
        indicator = session.query(EconomicIndicator).filter_by(code=code).first()
        if indicator is None:
            return pd.DataFrame(columns=["date", "value"])

        query = (
            session.query(EconomicDataPoint.date, EconomicDataPoint.value)
            .filter(EconomicDataPoint.indicator_id == indicator.id)
        )
        if start is not None:
            query = query.filter(EconomicDataPoint.date >= start)
        if end is not None:
            query = query.filter(EconomicDataPoint.date <= end)

        rows = query.order_by(EconomicDataPoint.date.asc()).all()
        if not rows:
            return pd.DataFrame(columns=["date", "value"])

        df = pd.DataFrame(rows, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["date", "value"]).drop_duplicates(subset=["date"]).sort_values("date")
        return df.reset_index(drop=True)
    finally:
        if owns_session:
            session.close()


def monthly_ffill(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a lower/higher-frequency series to month-end frequency,
    forward-filling the last available value within each month.

    Input expects columns date/value.
    """
    if df.empty:
        return df.copy()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.set_index("date").sort_index()
    out = out.resample("M").last().ffill()
    out = out.reset_index()
    return out[["date", "value"]]


def compute_output_gap(
    session: Optional[Session] = None,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    gdp_actual_code: str = "GDPC1",
    gdp_potential_code: str = "GDPPOT",
) -> pd.DataFrame:
    """
    Compute output gap from FRED real GDP and potential real GDP:

        gap = (GDPC1 - GDPPOT) / GDPPOT * 100

    Both series are typically quarterly; result is returned as a
    month-end series via forward-fill.
    """
    owns_session = session is None
    if session is None:
        session = SessionLocal()
    try:
        actual = load_indicator_series_by_code(
            gdp_actual_code, session, start=start, end=end
        )
        potential = load_indicator_series_by_code(
            gdp_potential_code, session, start=start, end=end
        )
        if actual.empty or potential.empty:
            return pd.DataFrame(columns=["date", "value"])

        actual_q = actual.copy()
        potential_q = potential.copy()
        actual_q["period"] = actual_q["date"].dt.to_period("Q")
        potential_q["period"] = potential_q["date"].dt.to_period("Q")

        merged = pd.merge(
            actual_q[["period", "value"]].rename(columns={"value": "actual"}),
            potential_q[["period", "value"]].rename(columns={"value": "potential"}),
            on="period",
            how="inner",
        ).sort_values("period")

        if merged.empty:
            return pd.DataFrame(columns=["date", "value"])

        merged["gap"] = (merged["actual"] - merged["potential"]) / merged["potential"] * 100.0
        merged["date"] = merged["period"].dt.end_time.dt.to_pydatetime()

        gap_q = merged[["date", "gap"]].rename(columns={"gap": "value"})
        gap_q["value"] = pd.to_numeric(gap_q["value"], errors="coerce")
        gap_q = gap_q.dropna(subset=["value"])
        return monthly_ffill(gap_q)
    finally:
        if owns_session:
            session.close()

