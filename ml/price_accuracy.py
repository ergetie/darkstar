"""Shared price forecast accuracy computation.

One implementation (database fetch plus pure maths) used by the
``/api/price-forecast/accuracy`` endpoint and by the planner's price reserve, so
both always report the same numbers. Accuracy compares the stored ``spot_p50`` of
a given forecast horizon (``days_ahead``) against the actual spot price recorded
in ``slot_observations`` over the last 7 days.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# A forecast needs at least this many distinct days of paired data to be trusted.
MIN_SAMPLE_DAYS = 2

STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient_data"


@dataclass(frozen=True)
class ForecastAccuracy:
    """Accuracy of one forecast horizon (SEK/kWh, spot domain).

    Error is ``spot_p50 - actual spot`` per slot. ``mae``, ``bias`` and
    ``debiased_mae`` are ``None`` unless ``status == "ok"``.
    """

    mae: float | None
    bias: float | None
    debiased_mae: float | None
    sample_days: int
    status: str

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


def fetch_accuracy_rows(db_path: str, days_ahead: int = 1) -> list[sqlite3.Row]:
    """Forecast/actual pairs of the last 7 days for one forecast horizon."""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT pf.slot_start, pf.spot_p50, so.export_price_sek_kwh
            FROM price_forecasts pf
            JOIN slot_observations so ON so.slot_start = pf.slot_start
            WHERE pf.days_ahead = ?
              AND pf.spot_p50 IS NOT NULL
              AND so.export_price_sek_kwh IS NOT NULL
              AND pf.slot_start >= datetime('now', '-7 days')
            """,
            (int(days_ahead),),
        )
        return list(cursor.fetchall())
    finally:
        conn.close()


def compute_forecast_accuracy(
    rows: Sequence[Any],
) -> ForecastAccuracy:
    """Bias, MAE and de-biased MAE of forecast/actual rows.

    ``bias`` is mean(e), ``mae`` mean(|e|), ``debiased_mae`` mean(|e - bias|) with
    ``e = spot_p50 - export_price_sek_kwh``. Fewer than ``MIN_SAMPLE_DAYS``
    distinct ``slot_start`` dates gives ``insufficient_data``.
    """
    errors = [float(r["spot_p50"]) - float(r["export_price_sek_kwh"]) for r in rows]
    sample_days = len({r["slot_start"][:10] for r in rows})
    if sample_days < MIN_SAMPLE_DAYS or not errors:
        return ForecastAccuracy(None, None, None, sample_days, STATUS_INSUFFICIENT)
    bias = sum(errors) / len(errors)
    return ForecastAccuracy(
        mae=sum(abs(e) for e in errors) / len(errors),
        bias=bias,
        debiased_mae=sum(abs(e - bias) for e in errors) / len(errors),
        sample_days=sample_days,
        status=STATUS_OK,
    )


def load_forecast_accuracy(db_path: str, days_ahead: int = 1) -> ForecastAccuracy:
    """Fetch and compute the accuracy of one horizon (raises on database errors)."""
    return compute_forecast_accuracy(fetch_accuracy_rows(db_path, days_ahead))
