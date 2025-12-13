from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
import math
from typing import Dict, Iterable, List, Optional


class ModelType(str, Enum):
    """Supported Taylor rule variants."""

    TAYLOR = "taylor"
    EXTENDED = "extended"
    RUDEBUSCH = "rudebusch"
    MANKIW = "mankiw"
    EVANS = "evans"
    STONE = "stone"


@dataclass(frozen=True)
class TaylorRuleParams:
    """
    Unified parameters for Taylor rule variants.

    This object is intended to be stable across UI/backend integrations.
    Values are interpreted as percentages (e.g., 4.2 means 4.2%).
    """

    model: ModelType = ModelType.TAYLOR
    real_rate: float = 2.0
    target_inflation: float = 2.0
    alpha: float = 0.5
    beta: float = 0.5
    okun: float = 0.5
    nairu: float = 5.5
    intercept: float = 0.0
    rho: float = 0.0

    # Optional data series values (for a single timestamp)
    core_inflation: float = 0.0
    unemployment_rate: float = 0.0
    output_gap: float = 0.0
    prev_fed_rate: float = 0.0
    survey_rate: float = 0.0


@dataclass(frozen=True)
class RatePoint:
    date: date
    taylor: float
    fed: float
    survey: float
    adjusted: float

    # Diagnostics (optional, used by UI)
    inflation: Optional[float] = None
    unemployment: Optional[float] = None
    nairu: Optional[float] = None
    output_gap: Optional[float] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "date": self.date.isoformat(),
            "taylor": self.taylor,
            "fed": self.fed,
            "survey": self.survey,
            "adjusted": self.adjusted,
            "inflation": self.inflation,
            "unemployment": self.unemployment,
            "nairu": self.nairu,
            "output_gap": self.output_gap,
        }


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


def model_defaults(model: ModelType) -> TaylorRuleParams:
    overrides = MODEL_PRESETS.get(model, {})
    return replace(TaylorRuleParams(), model=model, **overrides)


def _safe_float(value: object) -> float:
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(num):
        return 0.0
    return num


def calculate_rate(params: TaylorRuleParams) -> float:
    """
    Compute a Taylor-rule-style policy rate.

    Current implementation follows the simplified form used in the simulator:
        i = r* + π + α(π-π*) + β·okun·(u*-u) + output_gap + intercept
    """
    inflation = _safe_float(params.core_inflation)
    inflation_gap = inflation - _safe_float(params.target_inflation)
    unemployment_gap = _safe_float(params.nairu) - _safe_float(params.unemployment_rate)

    rate = (
        _safe_float(params.real_rate)
        + inflation
        + _safe_float(params.alpha) * inflation_gap
        + _safe_float(params.beta) * _safe_float(params.okun) * unemployment_gap
        + _safe_float(params.output_gap)
        + _safe_float(params.intercept)
    )
    return _safe_float(rate)


def calculate_adjusted_rate(taylor_rate: float, prev_fed_rate: float, rho: float) -> float:
    """Apply policy inertia / smoothing."""
    taylor = _safe_float(taylor_rate)
    prev_rate = _safe_float(prev_fed_rate)
    weight = max(0.0, min(1.0, _safe_float(rho)))
    return _safe_float(weight * prev_rate + (1.0 - weight) * taylor)


def latest_metrics(params: TaylorRuleParams, time_series: Iterable[RatePoint]) -> Dict[str, float]:
    series_list = list(time_series)
    if not series_list:
        return {"taylorLatest": 0.0, "fedLatest": 0.0, "spread": 0.0, "difference": 0.0}

    latest = series_list[-1]
    spread = latest.fed - latest.taylor
    return {
        "taylorLatest": float(latest.taylor),
        "fedLatest": float(latest.fed),
        "spread": float(spread),
        "difference": float(spread),
    }

