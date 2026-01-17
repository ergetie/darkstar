"""
Battery Cost Calculator Module

Tracks the weighted average cost of energy stored in the battery.
This is used by Kepler to make optimal export decisions.

Algorithm (weighted average):
- Grid charge: cost = (old_kwh * old_cost + charge_kwh * price) / new_kwh
- PV charge (free): cost = (old_kwh * old_cost) / (old_kwh + pv_kwh) (dilutes cost)
- Discharge: cost stays same (we're removing energy, not changing cost per kWh)
"""

import logging
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.learning.models import BatteryCost

# Default cost when no data is available (conservative to prevent aggressive export)
DEFAULT_BATTERY_COST_SEK_PER_KWH = 1.0

logger = logging.getLogger(__name__)


class BatteryCostTracker:
    """Tracks battery energy cost using weighted average using SQLAlchemy."""

    def __init__(self, db_path: str, capacity_kwh: float):
        """
        Initialize the battery cost tracker.

        Args:
            db_path: Path to SQLite database
            capacity_kwh: Battery capacity in kWh
        """
        self.db_path = db_path
        self.capacity_kwh = capacity_kwh

        # Initialize SQLAlchemy
        connect_args = {"check_same_thread": False, "timeout": 30.0}
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args=connect_args)
        self.Session = sessionmaker(bind=self.engine)

        # Table is managed by Alembic, but we can ensure it exists for standalone tests
        # self._ensure_table()

    def get_current_cost(self) -> float:
        """
        Get the current average battery cost per kWh.

        Returns:
            Current cost in SEK/kWh, or DEFAULT if no data
        """
        try:
            with self.Session() as session:
                cost = session.query(BatteryCost.avg_cost_sek_per_kwh).filter_by(id=1).scalar()
                if cost is not None:
                    return float(cost)
        except Exception as exc:
            logger.warning("Failed to read battery cost: %s", exc)

        return DEFAULT_BATTERY_COST_SEK_PER_KWH

    def get_state(self) -> dict:
        """
        Get full battery cost state for debugging.

        Returns:
            Dict with cost, energy, and updated_at
        """
        try:
            with self.Session() as session:
                row = session.get(BatteryCost, 1)
                if row:
                    return {
                        "avg_cost_sek_per_kwh": row.avg_cost_sek_per_kwh,
                        "energy_kwh": row.energy_kwh,
                        "updated_at": row.updated_at,
                    }
        except Exception as exc:
            logger.warning("Failed to read battery cost state: %s", exc)

        return {
            "avg_cost_sek_per_kwh": DEFAULT_BATTERY_COST_SEK_PER_KWH,
            "energy_kwh": 0.0,
            "updated_at": None,
        }

    def update_cost(
        self,
        current_soc_percent: float,
        grid_charge_kwh: float,
        pv_charge_kwh: float,
        import_price_sek: float,
    ) -> float:
        """
        Update battery cost based on charging activity.

        Args:
            current_soc_percent: Current battery SoC (0-100)
            grid_charge_kwh: Energy charged from grid this slot
            pv_charge_kwh: Energy charged from PV (free) this slot
            import_price_sek: Current import price in SEK/kWh

        Returns:
            New average cost in SEK/kWh
        """
        # Get current state
        state = self.get_state()
        old_cost = state["avg_cost_sek_per_kwh"]

        # Calculate current energy from SoC
        current_energy_kwh = (current_soc_percent / 100.0) * self.capacity_kwh

        # Start with current energy as base (may differ from last recorded due to discharge)
        new_energy_kwh = current_energy_kwh

        # Calculate new weighted average cost
        if grid_charge_kwh > 0.01:
            # Grid charging: add expensive energy
            old_total_cost = (current_energy_kwh - grid_charge_kwh) * old_cost
            new_cost_added = grid_charge_kwh * import_price_sek

            if new_energy_kwh > 0.01:
                new_cost = (old_total_cost + new_cost_added) / new_energy_kwh
            else:
                new_cost = import_price_sek
        elif pv_charge_kwh > 0.01:
            # PV charging: dilute cost with free energy
            # The energy before PV was added
            energy_before_pv = current_energy_kwh - pv_charge_kwh
            if energy_before_pv > 0.01:
                old_total_cost = energy_before_pv * old_cost
                # New energy is higher, cost stays same -> cost per kWh drops
                new_cost = old_total_cost / new_energy_kwh
            else:
                # Battery was empty, PV charging is free
                new_cost = 0.0
        else:
            # No significant charging, keep existing cost
            new_cost = old_cost

        # Clamp cost to reasonable bounds
        new_cost = max(0.0, min(new_cost, 10.0))  # 0-10 SEK/kWh

        # Persist to database
        try:
            with self.Session() as session:
                session.execute(
                    text(
                        "INSERT OR REPLACE INTO battery_cost (id, avg_cost_sek_per_kwh, energy_kwh, updated_at) "
                        "VALUES (1, :cost, :energy, :updated_at)"
                    ),
                    {
                        "cost": new_cost,
                        "energy": new_energy_kwh,
                        "updated_at": datetime.now().isoformat(),
                    },
                )
                session.commit()

            logger.info(
                "Battery cost updated: %.3f SEK/kWh (energy: %.2f kWh, grid: %.2f, pv: %.2f, price: %.2f)",
                new_cost,
                new_energy_kwh,
                grid_charge_kwh,
                pv_charge_kwh,
                import_price_sek,
            )
        except Exception as exc:
            logger.error("Failed to update battery cost: %s", exc)

        return new_cost

    def reset(self, cost: float = DEFAULT_BATTERY_COST_SEK_PER_KWH) -> None:
        """Reset battery cost to a specific value using SQLAlchemy."""
        try:
            with self.Session() as session:
                session.execute(
                    text(
                        "INSERT OR REPLACE INTO battery_cost (id, avg_cost_sek_per_kwh, energy_kwh, updated_at) "
                        "VALUES (1, :cost, 0.0, :updated_at)"
                    ),
                    {"cost": cost, "updated_at": datetime.now().isoformat()},
                )
                session.commit()
            logger.info("Battery cost reset to %.3f SEK/kWh", cost)
        except Exception as exc:
            logger.error("Failed to reset battery cost: %s", exc)
