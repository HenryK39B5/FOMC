"""Rule-based rate models used across the project."""

from .taylor import (  # noqa: F401
    DEFAULT_PARAMS,
    MODEL_PRESETS,
    ModelType,
    RatePoint,
    TaylorRuleParams,
    calculate_adjusted_rate,
    calculate_rate,
    generate_time_series,
    latest_metrics,
    model_defaults,
)
