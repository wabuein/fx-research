from __future__ import annotations

from typing import NamedTuple

import pandas as pd

from fxresearch.structure.aoi import RESISTANCE, SUPPORT
from fxresearch.structure.pivots import Pivot


class Corner(NamedTuple):

    price: float
    side: str
    tf: str


class CornerHandler:

    def __init__(self, fresh_count: int = 2) -> None:
        self.fresh_count = fresh_count

    def fresh_corners(self, times: pd.DatetimeIndex, pivots: dict[str, list[Pivot]],
                      keys: tuple[str, ...] | list[str]) -> list[list[Corner]]:
        corners: list[list[Corner]] = [[] for _ in range(len(times))]

        for key in keys:
            pivot_list = pivots.get(key, [])
            if not pivot_list: continue

            # pivots confirmed strictly before each bar opens, the last fresh_count of them per bar
            confirm_times = pd.DatetimeIndex([pivot.confirm for pivot in pivot_list])
            positions = confirm_times.searchsorted(times, side="left")
            for i in range(len(times)):
                k = int(positions[i])
                for pivot in pivot_list[max(0, k - self.fresh_count):k]:
                    corners[i].append(Corner(float(pivot.price), RESISTANCE if pivot.kind == "H" else SUPPORT, key))

        return corners

    def react_at(self, levels: list[Corner], low: float, high: float, close: float, direction: str,
                 atr: float, tol_atr: float) -> Corner | None:
        tol = tol_atr * atr
        side = SUPPORT if direction == "long" else RESISTANCE

        # a long wicks into support and closes back above it, a short the mirror image
        for level in levels:
            if level.side != side: continue
            if direction == "long" and low <= level.price + tol and close > level.price: return level
            if direction == "short" and high >= level.price - tol and close < level.price: return level

        return None

