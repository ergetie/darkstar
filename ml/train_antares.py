from __future__ import annotations

"""
Offline Antares v1 training entrypoint (schema/stats only, no model yet).

Phase 2 (Rev 68): This script is responsible for:
  - Loading the stable Antares v1 slot dataset via ml.api.get_antares_slots.
  - Reporting basic dataset statistics (date range, counts, quality labels).
  - Acting as the canonical starting point for future Antares model training.
"""

from typing import Any, Dict

import numpy as np
import pandas as pd

from ml.api import get_antares_slots


def summarize_dataset(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"empty": True}

    df["episode_date"] = pd.to_datetime(df["episode_date"])
    dates = df["episode_date"].sort_values()
    status_counts = df["data_quality_status"].value_counts().to_dict()

    features = {
        "load_kwh": df["load_kwh"],
        "pv_kwh": df["pv_kwh"],
        "import_kwh": df["import_kwh"],
        "export_kwh": df["export_kwh"],
    }

    def _basic_stats(series: pd.Series) -> Dict[str, float]:
        series = series.astype(float)
        return {
            "mean": float(series.mean()),
            "std": float(series.std() or 0.0),
            "min": float(series.min()),
            "max": float(series.max()),
        }

    feature_stats = {name: _basic_stats(col) for name, col in features.items()}

    result: Dict[str, Any] = {
        "empty": False,
        "slots": int(len(df)),
        "episodes": int(df["episode_id"].nunique()),
        "days": int(dates.dt.date.nunique()),
        "date_min": dates.min().date().isoformat(),
        "date_max": dates.max().date().isoformat(),
        "data_quality_counts": status_counts,
        "feature_stats": feature_stats,
    }
    return result


def main() -> int:
    df = get_antares_slots(dataset_version="v1")
    summary = summarize_dataset(df)
    print("[antares] dataset summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

