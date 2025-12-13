from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import Enum
import math
from typing import Dict, Iterable, List, Union


class ModelType(str, Enum):
    """Supported Taylor rule variants."""

    TAYLOR = "taylor"
    EXTENDED = "extended"
    RUDEBUSCH = "rudebusch"
    MANKIW = "mankiw"
    EVANS = "evans"
    STONE = "stone"


DateLike = Union[str, date, datetime]


@dataclass(frozen=True)
class TaylorRuleParams:
    """Input payload for Taylor rule calculations."""

    real_rate: float = 0.0
    core_inflation: float = 0.0
    target_inflation: float = 0.0
    alpha: float = 0.0
    nairu: float = 0.0
    unemployment_rate: float = 0.0
    beta: float = 0.0
    okun: float = 1.0
    output_gap: float = 0.0
    intercept: float = 0.0
    prev_fed_rate: float = 0.0
    rho: float = 0.0
    survey_rate: float = 0.0
    start_date: date = date(2020, 1, 1)
    end_date: date = date(2024, 12, 31)
    model: ModelType = ModelType.TAYLOR


@dataclass(frozen=True)
class RatePoint:
    """Single observation for a simulated time series."""

    date: date
    taylor: float
    fed: float
    survey: float
    adjusted: float

    def as_dict(self) -> Dict[str, Union[str, float]]:
        return {
            "date": self.date.isoformat(),
            "taylor": self.taylor,
            "fed": self.fed,
            "survey": self.survey,
            "adjusted": self.adjusted,
        }


DEFAULT_PARAMS = TaylorRuleParams(
    real_rate=2.0,
    core_inflation=5.96,
    target_inflation=2.0,
    alpha=0.5,
    nairu=4.4,
    unemployment_rate=4.0,
    beta=0.5,
    okun=0.5,
    prev_fed_rate=2.0,
    rho=0.0,
    survey_rate=3.75,
    output_gap=0.0,
    intercept=0.0,
    start_date=date(2015, 11, 30),
    end_date=date(2025, 11, 30),
    model=ModelType.TAYLOR,
)


MODEL_PRESETS: Dict[ModelType, Dict[str, float]] = {
    ModelType.TAYLOR: {
        "real_rate": 2.0,
        "alpha": 0.5,
        "target_inflation": 2.0,
        "beta": 0.5,
        "okun": 0.5,
        "nairu": 5.5,
    },
    ModelType.EXTENDED: {
        "real_rate": 2.0,
        "alpha": 0.5,
        "target_inflation": 2.0,
        "beta": 1.0,
        "okun": 2.0,
        "nairu": 5.6,
    },
    ModelType.RUDEBUSCH: {
        "real_rate": 2.0,
        "alpha": 0.5,
        "target_inflation": 2.0,
        "beta": 1.0,
        "okun": 2.0,
        "nairu": 5.6,
    },
    ModelType.MANKIW: {
        "real_rate": 1.4,
        "alpha": 0.4,
        "target_inflation": 0.0,
        "beta": 1.8,
        "okun": 1.0,
        "nairu": 5.6,
    },
    ModelType.EVANS: {
        "real_rate": 4.0,
        "alpha": 0.5,
        "target_inflation": 2.5,
        "beta": 0.5,
        "okun": 2.0,
        "nairu": 5.0,
    },
    ModelType.STONE: {
        "real_rate": 2.0,
        "alpha": 0.5,
        "target_inflation": 1.75,
        "beta": 0.75,
        "okun": 2.0,
        "nairu": 5.0,
    },
}


def _safe_float(value: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(num):
        return 0.0
    return num


def _coerce_date(value: DateLike) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Unsupported date input: {value!r}")


def model_defaults(model: ModelType) -> TaylorRuleParams:
    """Return a fresh params object for a given model preset."""
    overrides = MODEL_PRESETS.get(model, {})
    return replace(DEFAULT_PARAMS, model=model, **overrides)


def calculate_rate(params: TaylorRuleParams) -> float:
    """Compute the Taylor rule (or variant) rate."""
    inflation_gap = _safe_float(params.core_inflation) - _safe_float(params.target_inflation)
    unemployment_gap = _safe_float(params.nairu) - _safe_float(params.unemployment_rate)

    rate = (
        _safe_float(params.real_rate)
        + _safe_float(params.core_inflation)
        + _safe_float(params.alpha) * inflation_gap
        + _safe_float(params.beta) * _safe_float(params.okun) * unemployment_gap
        + _safe_float(params.output_gap)
        + _safe_float(params.intercept)
    )
    return _safe_float(rate)


def calculate_adjusted_rate(taylor_rate: float, prev_fed_rate: float, rho: float) -> float:
    """Apply policy inertia to the model-implied rate."""
    taylor = _safe_float(taylor_rate)
    prev_rate = _safe_float(prev_fed_rate)
    weight = max(0.0, min(1.0, _safe_float(rho)))
    return _safe_float(weight * prev_rate + (1 - weight) * taylor)


def generate_time_series(params: TaylorRuleParams) -> List[RatePoint]:
    """Simulate a monthly time series using trend assumptions (placeholder for real data)."""
    start = _coerce_date(params.start_date)
    end = _coerce_date(params.end_date)
    days = max((end - start).days, 0)
    months = max(int(days / 30.44), 1)

    series: List[RatePoint] = []
    prev_rate = _safe_float(params.prev_fed_rate)

    for i in range(months + 1):
        current_date = start + timedelta(days=int(i * 30.44))

        if i == months:
            adjusted_unemployment = params.unemployment_rate
            adjusted_inflation = params.core_inflation
        else:
            adjusted_unemployment = max(
                3.5,
                _safe_float(params.unemployment_rate) - (i / months) * 0.5,
            )
            adjusted_inflation = max(
                _safe_float(params.target_inflation),
                _safe_float(params.core_inflation)
                - (i / months) * (_safe_float(params.core_inflation) - _safe_float(params.target_inflation)) * 0.8,
            )

        adjusted_output_gap = _safe_float(params.output_gap) + math.sin(i / 20) * 2

        series_params = replace(
            params,
            core_inflation=adjusted_inflation,
            unemployment_rate=adjusted_unemployment,
            output_gap=adjusted_output_gap,
        )
        taylor_rate = calculate_rate(series_params)
        adjusted_rate = calculate_adjusted_rate(taylor_rate, prev_rate, params.rho)

        fed_rate = min(5.33, _safe_float(params.prev_fed_rate) + (i / months) * 3.33)
        prev_rate = taylor_rate

        series.append(
            RatePoint(
                date=current_date,
                taylor=round(taylor_rate, 2),
                fed=round(fed_rate, 2),
                survey=round(_safe_float(params.survey_rate), 2),
                adjusted=round(adjusted_rate, 2),
            )
        )

    return series


def latest_metrics(params: TaylorRuleParams, time_series: Iterable[RatePoint]) -> Dict[str, float]:
    """Compute headline metrics from a simulated series."""
    series_list = list(time_series)
    if not series_list:
        return {
            "taylorLatest": 0.0,
            "fedLatest": 0.0,
            "spread": 0.0,
            "difference": 0.0,
        }

    latest = series_list[-1]
    spread = latest.fed - latest.taylor
    return {
        "taylorLatest": latest.taylor,
        "fedLatest": latest.fed,
        "spread": spread,
        "difference": spread,
    }
