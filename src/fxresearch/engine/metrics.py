from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# in-sample is every trade before this year, out-of-sample from it onwards
SPLIT_YEAR = 2022


@dataclass(frozen=True)
class Performance:

    n: int
    win_pct: float
    net: float
    avg: float
    pf: float
    max_dd: float
    expectancy: float

    def describe(self) -> str:
        pf = "inf" if self.pf == float("inf") else f"{self.pf:.2f}"
        return (f"n={self.n:>4}  win={self.win_pct:>4}%  net={self.net:>7}R  "
                f"avg={self.avg:>+.4f}R  PF={pf:>5}  maxDD={self.max_dd:>6}R")


EMPTY_PERFORMANCE = Performance(0, 0, 0, 0, 0, 0, 0)


def measure(trades: list[Any], column: str = "r_net") -> Performance:
    if not trades: return EMPTY_PERFORMANCE

    r = np.array([getattr(trade, column) for trade in trades])
    wins, losses = r[r > 0].sum(), abs(r[r < 0].sum())
    equity = np.cumsum(r)
    drawdown = float((np.maximum.accumulate(equity) - equity).max())

    return Performance(
        n=len(r),
        win_pct=round(100 * (r > 0).mean(), 1),
        net=round(float(r.sum()), 1),
        avg=round(float(r.mean()), 4),
        pf=round(float(wins / losses), 2) if losses > 0 else float("inf"),
        max_dd=round(drawdown, 1),
        expectancy=round(float(r.mean()), 4),
    )


def in_sample(trades: list[Any]) -> list[Any]:
    return [trade for trade in trades if trade.year < SPLIT_YEAR]


def out_of_sample(trades: list[Any]) -> list[Any]:
    return [trade for trade in trades if trade.year >= SPLIT_YEAR]
