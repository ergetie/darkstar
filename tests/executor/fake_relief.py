"""Instant trigger for tests of the give-way ladder independently of fuse timing."""

from datetime import datetime

from executor.config import LoadBalancingConfig
from executor.fuse_model import Relief


class InstantRelief:
    def __init__(self, config: LoadBalancingConfig, tolerance_a: float = 0):
        self.config = config
        self.tolerance_a = tolerance_a
        self.hot: set[int] = set()

    def relief_needed(self, phase: int, momentary_a: float, now: datetime, stale: bool) -> Relief:
        rating = self.config.main_fuse_a or 0
        if stale:
            return Relief()
        return Relief(max(0, momentary_a - rating - self.tolerance_a), momentary_a > rating * 1.25)

    def cooled(self, phases: list[int]) -> bool:
        return not self.hot.intersection(phases)
