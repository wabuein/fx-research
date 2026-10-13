from __future__ import annotations

import statistics
from dataclasses import dataclass

import pandas as pd

from fxresearch.structure.pivots import Pivot

RESISTANCE = "resistance"
SUPPORT = "support"
SIDES = (("H", RESISTANCE), ("L", SUPPORT))


@dataclass(frozen=True)
class Aoi:

    tf: str
    kind: str
    side: str
    price: float
    touches: int
    score: float = 0.0

    def describe(self) -> str:
        return f"{self.tf} {self.kind} {self.side} {self.price:.6f} x{self.touches}"


class AoiHandler:

    def __init__(self, timeframes: tuple[str, ...] = ("D", "W")) -> None:
        self.timeframes = timeframes

    def confirmed_before(self, frames: dict, tf: str, signal_time: pd.Timestamp) -> list[Pivot]:
        return [pivot for pivot in frames["pivots"][tf] if pivot.confirm < signal_time]

    def build_v1_levels(self, frames: dict, signal_time: pd.Timestamp, atr_1h: float,
                        price: float) -> tuple[list[Aoi], list[Aoi]]:
        levels: list[Aoi] = []
        clusters: list[Aoi] = []
        tolerance = max(0.75 * atr_1h, abs(price) * 0.001)

        for tf in self.timeframes:
            pivots = self.confirmed_before(frames, tf, signal_time)
            if len(pivots) >= 2:
                levels += [Aoi(tf, "latest_swing_endpoint", self._side(p), float(p.price), 1) for p in pivots[-2:]]

            recent = pivots[-40:]
            for pivot_type, side in SIDES:
                values = sorted(float(p.price) for p in recent if p.kind == pivot_type)
                clusters += self._sequential_clusters(tf, side, values, tolerance)

        return levels, clusters

    def build_corner_aois(self, frames: dict, signal_time: pd.Timestamp, price: float, atr_1h: float,
                          lookback_pivots: int, tolerance_atr: float, latest_scores: tuple[float, float],
                          weekly_cluster_mult: float) -> list[Aoi]:
        tolerance = self.corner_tolerance(price, atr_1h, tolerance_atr)
        aois: list[Aoi] = []

        for tf in self.timeframes:
            pivots = self.confirmed_before(frames, tf, signal_time)
            if len(pivots) >= 2:
                score = latest_scores[0] if tf == "D" else latest_scores[1]
                aois += [Aoi(tf, "latest_corner", self._side(p), float(p.price), 1, score) for p in pivots[-2:]]

            recent = pivots[-lookback_pivots:]
            for pivot_type, side in SIDES:
                values = sorted(float(p.price) for p in recent if p.kind == pivot_type)
                for bucket in self._nearest_buckets(values, tolerance):
                    if len(bucket) < 2: continue

                    touches = len(bucket)
                    score = touches * (1.0 if tf == "D" else weekly_cluster_mult)
                    aois.append(Aoi(tf, "corner_cluster", side, statistics.mean(bucket), touches, score))

        return aois

    def corner_tolerance(self, price: float, atr_1h: float, tolerance_atr: float) -> float:
        return max(tolerance_atr * atr_1h, abs(price) * 0.0007)

    def best_reaction(self, aois: list[Aoi], candle: pd.Series, direction: str, atr_1h: float) -> Aoi | None:
        tolerance = 0.75 * atr_1h
        close = float(candle.Close)
        matches = []

        for aoi in aois:
            if direction == "long" and aoi.side == SUPPORT:
                if float(candle.Low) <= aoi.price + tolerance and close > aoi.price:
                    matches.append(aoi)
            elif direction == "short" and aoi.side == RESISTANCE:
                if float(candle.High) >= aoi.price - tolerance and close < aoi.price:
                    matches.append(aoi)

        if not matches: return None
        return sorted(matches, key=lambda a: (-a.score, abs(close - float(a.price))))[0]

    def target_candidates(self, aois: list[Aoi], direction: str, entry: float, risk: float, min_rr: float,
                          max_rr: float) -> list[tuple[Aoi, float]]:
        candidates = []

        for aoi in aois:
            price = float(aoi.price)
            if direction == "long" and aoi.side == RESISTANCE and price > entry:
                rr = (price - entry) / risk
            elif direction == "short" and aoi.side == SUPPORT and price < entry:
                rr = (entry - price) / risk
            else:
                continue

            if min_rr <= rr <= max_rr:
                candidates.append((aoi, rr))

        return candidates

    def dedupe(self, aois: list[Aoi], tolerance: float) -> list[Aoi]:
        # keep the stronger of two same-side aois closer than half the cluster tolerance
        deduped: list[Aoi] = []

        for aoi in sorted(aois, key=lambda a: a.score, reverse=True):
            if any(aoi.side == other.side and abs(aoi.price - other.price) <= tolerance * 0.5 for other in deduped):
                continue
            deduped.append(aoi)

        return deduped

    def _sequential_clusters(self, tf: str, side: str, values: list[float], tolerance: float) -> list[Aoi]:
        clusters: list[Aoi] = []
        bucket: list[float] = []

        for value in values:
            if not bucket or abs(value - statistics.mean(bucket)) <= tolerance:
                bucket.append(value)
                continue

            if len(bucket) >= 2:
                clusters.append(Aoi(tf, "cluster", side, statistics.mean(bucket), len(bucket)))
            bucket = [value]

        if len(bucket) >= 2:
            clusters.append(Aoi(tf, "cluster", side, statistics.mean(bucket), len(bucket)))

        return clusters

    def _nearest_buckets(self, values: list[float], tolerance: float) -> list[list[float]]:
        buckets: list[list[float]] = []

        for value in values:
            for bucket in buckets:
                if abs(value - statistics.mean(bucket)) <= tolerance:
                    bucket.append(value)
                    break
            else:
                buckets.append([value])

        return buckets

    def _side(self, pivot: Pivot) -> str:
        return RESISTANCE if pivot.kind == "H" else SUPPORT

