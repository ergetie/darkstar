"""
RL v2 state/action contract (Rev 84).

This module defines the *intended* v2 state and action spaces for
Antares RL experiments. It is not yet wired into the production
planner; it is a reference for lab work under ml/rl_v2/.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class RlV2StateSpec:
    """
    Sequence-based RL v2 state.

    Intended layout (per time step):
        - current_soc_percent: float
        - hour_of_day: float
        - price_seq: array[seq_len] of normalized import prices
        - net_load_seq: array[seq_len] of normalized (load - pv)
    """

    seq_len: int = 48  # e.g. next 12h at 15min resolution

    @property
    def flat_dim(self) -> int:
        # 2 scalars + 2 sequences of length seq_len
        return 2 + 2 * self.seq_len


@dataclass
class RlV2ActionSpec:
    """
    RL v2 action space.

    Intended layout:
        - battery_charge_kw
        - battery_discharge_kw
        - export_kw
    """

    def bounds(self) -> Tuple[float, float]:
        # Symmetric generic bounds; concrete env should clamp to config.
        return 0.0, 10.0
