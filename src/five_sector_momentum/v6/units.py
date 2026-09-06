from __future__ import annotations

UNIT_REGISTRY = {
    "raw_price": "price_points",
    "panama_adjusted_price": "price_points",
    "point_return": "price_points_per_contract",
    "forecast_score": "annualized_point_sharpe_dimensionless",
    "tick_size": "price_points_per_tick",
    "contract_multiplier": "cny_per_price_point_per_lot",
    "position": "integer_lots",
    "turnover": "lots_or_cny_notional_as_explicitly_labelled",
    "commission": "cny",
    "slippage": "cny",
    "margin_rate": "decimal_fraction",
    "margin": "cny",
    "pnl": "cny",
    "equity": "cny",
    "daily_return": "decimal_fraction",
    "volatility": "annualized_decimal_fraction",
}


def validate_units() -> None:
    if UNIT_REGISTRY["forecast_score"] != "annualized_point_sharpe_dimensionless":
        raise ValueError("v6 signal units must remain absolute point differences")
    if UNIT_REGISTRY["position"] != "integer_lots":
        raise ValueError("positions must be integer lots")

