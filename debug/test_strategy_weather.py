from __future__ import annotations

import yaml

from backend.strategy.engine import StrategyEngine


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main() -> None:
    config = load_config()
    engine = StrategyEngine(config)

    s_index_cfg = config.get("s_index", {}) or {}
    base_pv_weight = float(s_index_cfg.get("pv_deficit_weight", 0.0) or 0.0)
    base_temp_weight = float(s_index_cfg.get("temp_weight", 0.0) or 0.0)

    input_data = {
        "context": {
            "vacation_mode": False,
            "weather_volatility": {
                "cloud": 0.9,
                "temp": 0.9,
            },
        }
    }

    overrides = engine.decide(input_data)
    s_index_overrides = overrides.get("s_index") or {}

    pv_weight = float(s_index_overrides.get("pv_deficit_weight", base_pv_weight))
    temp_weight = float(s_index_overrides.get("temp_weight", base_temp_weight))

    assert pv_weight >= base_pv_weight, "PV weight should not decrease with volatility"
    assert temp_weight >= base_temp_weight, "Temp weight should not decrease with volatility"

    print("Base pv_deficit_weight:", base_pv_weight)
    print("Adjusted pv_deficit_weight:", pv_weight)
    print("Base temp_weight:", base_temp_weight)
    print("Adjusted temp_weight:", temp_weight)
    print("Delta temp_weight:", temp_weight - base_temp_weight)
    print("Overrides:", overrides)


if __name__ == "__main__":
    main()
