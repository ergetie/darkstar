from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import lightgbm as lgb
import numpy as np


@dataclass
class AntaresPolicyV1:
    """
    Simple MPC-imitating policy for Antares v1.

    This wraps a set of LightGBM regressors trained on AntaresMPCEnv
    state vectors and predicts per-slot control signals.
    """

    batt_charge_model: lgb.Booster | None
    batt_discharge_model: lgb.Booster | None
    export_model: lgb.Booster | None

    @classmethod
    def load_from_dir(cls, path: str | Path) -> "AntaresPolicyV1":
        base = Path(path)
        charge_path = base / "policy_batt_charge_kw.lgb"
        discharge_path = base / "policy_batt_discharge_kw.lgb"
        export_path = base / "policy_export_kw.lgb"

        charge = lgb.Booster(model_file=str(charge_path)) if charge_path.exists() else None
        discharge = lgb.Booster(model_file=str(discharge_path)) if discharge_path.exists() else None
        export = lgb.Booster(model_file=str(export_path)) if export_path.exists() else None

        return cls(
            batt_charge_model=charge,
            batt_discharge_model=discharge,
            export_model=export,
        )

    def predict(self, state: np.ndarray) -> Dict[str, float]:
        """
        Predict per-slot control signals from a state vector.

        The state vector must match the layout produced by AntaresMPCEnv:
            [hour_of_day, load_forecast_kwh, pv_forecast_kwh,
             projected_soc_percent, import_price_sek_kwh, export_price_sek_kwh]
        """
        x = np.asarray(state, dtype=float).reshape(1, -1)
        result: Dict[str, float] = {}

        if self.batt_charge_model is not None:
            result["battery_charge_kw"] = float(self.batt_charge_model.predict(x)[0])
        else:
            result["battery_charge_kw"] = 0.0

        if self.batt_discharge_model is not None:
            result["battery_discharge_kw"] = float(self.batt_discharge_model.predict(x)[0])
        else:
            result["battery_discharge_kw"] = 0.0

        if self.export_model is not None:
            result["export_kw"] = float(self.export_model.predict(x)[0])
        else:
            result["export_kw"] = 0.0

        return result
