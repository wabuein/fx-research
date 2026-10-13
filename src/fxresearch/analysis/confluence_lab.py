from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from fxresearch.context import ResearchContext
from fxresearch.engine.indicators import atr
from fxresearch.paths import REPORTS_DIR, relative_to_root
from fxresearch.strategies.v3_4h_corner import FourHourCornerStrategy, V3Config
from fxresearch.structure.aoi import Aoi
from fxresearch.structure.candles import tier1_from_values

WARMUP = 60
MAX_HOLD_BARS = 60
LOOKBACK_PIVOTS = 80
CLUSTER_TOL_ATR = 0.75
ATR_BUFFER = 0.25
MIN_SL_ATR, MAX_SL_ATR = 0.8, 2.5
MIN_RR, MAX_RR = 1.25, 2.5
ENTRY_OFFSET = 2

# lens a: fixed 1x atr stop with targets spanning the win-rate versus rr frontier
LENS_A_TARGETS = {"a_R_0p5R": 0.5, "a_R_0p75R": 0.75, "a_R_1R": 1.0, "a_R_1p5R": 1.5, "a_R_2R": 2.0}


def agrees(state: str, direction: str) -> bool:
    return (state == "bullish" and direction == "long") or (state == "bearish" and direction == "short")


def barrier_r(direction: str, entry: np.ndarray, stop: np.ndarray, target: np.ndarray, high: np.ndarray,
              low: np.ndarray, close: np.ndarray, valid: np.ndarray, entry_offset: int = ENTRY_OFFSET,
              n_bars: int = MAX_HOLD_BARS) -> np.ndarray:
    # first barrier touched for every candidate at once; a bar touching both counts as the stop
    n = len(entry)
    risk = np.abs(entry - stop)
    realized = np.full(n, np.nan)
    resolved = ~valid | (risk <= 0)

    for m in range(entry_offset, entry_offset + n_bars + 1):
        length = n - m
        if length <= 0: break

        idx = np.arange(length)
        active = valid[idx] & ~resolved[idx]
        if not active.any(): continue

        hi = high[m:m + length]
        lo = low[m:m + length]
        if direction == "long":
            stop_hit = lo <= stop[idx]
            target_hit = hi >= target[idx]
        else:
            stop_hit = hi >= stop[idx]
            target_hit = lo <= target[idx]

        newly_stopped = active & stop_hit
        newly_targeted = active & target_hit & ~stop_hit
        rr = np.abs(target[idx] - entry[idx]) / np.where(risk[idx] == 0, np.nan, risk[idx])
        realized[idx[newly_stopped]] = -1.0
        realized[idx[newly_targeted]] = rr[newly_targeted]
        resolved[idx[newly_stopped | newly_targeted]] = True

    # still open after the hold window: mark to the last scanned close
    for i in np.where(valid & ~resolved)[0]:
        j = min(i + entry_offset + n_bars, n - 1)
        if risk[i] > 0:
            realized[i] = (close[j] - entry[i]) / risk[i] if direction == "long" else (entry[i] - close[j]) / risk[i]

    return realized


class ConfluenceLab:

    def __init__(self, context: ResearchContext, reports_dir: Path = REPORTS_DIR) -> None:
        self.reports_dir = reports_dir

        self.context = context
        self.v3 = FourHourCornerStrategy(V3Config(), context.reader, context.aois)

    def run(self, instruments: list[str]) -> None:
        path = self.reports_dir / "confluence_samples.csv"
        self.reports_dir.mkdir(exist_ok=True)
        first, total, done = True, 0, []

        for instrument in instruments:
            print(f"Processing {instrument} ...", flush=True)
            samples = self.process_instrument(instrument)
            if samples.empty:
                print(f"  no candidates for {instrument}")
                continue

            total += len(samples)
            samples.to_csv(path, mode="w" if first else "a", header=first, index=False)
            first = False
            done.append(instrument)
            print(f"  {len(samples)} candidates (running total {total})", flush=True)

        print(f"\nWrote {relative_to_root(path)}  ({total} candidates across {len(done)} instruments)")

    def asof_before(self, bar_times: pd.DatetimeIndex, timeline: pd.DataFrame) -> pd.DataFrame:
        # the latest timeline row strictly before each bar, in one merge
        if timeline.empty: return pd.DataFrame(index=range(len(bar_times)))

        left = pd.DataFrame({"t": bar_times})
        right = timeline.reset_index().rename(columns={"time": "t"}).sort_values("t")
        return pd.merge_asof(left.reset_index(), right, on="t", allow_exact_matches=False,
                             direction="backward").set_index("index")

    def at_aoi(self, aois: list[Aoi], candle: pd.Series, direction: str, atr_value: float,
               kind: str) -> tuple[bool, int, float]:
        tol = 0.75 * atr_value
        side = "support" if direction == "long" else "resistance"
        relevant = [a for a in aois if a.side == side and (kind == "any" or a.kind == kind)]
        matched = None
        nearest = None
        close = float(candle.Close)

        for aoi in relevant:
            price = float(aoi.price)
            distance = abs(close - price)
            if nearest is None or distance < nearest[0]:
                nearest = (distance, aoi)
            if direction == "long" and float(candle.Low) <= price + tol and close > price:
                matched = aoi if matched is None else matched
            if direction == "short" and float(candle.High) >= price - tol and close < price:
                matched = aoi if matched is None else matched

        touches = int(matched.touches) if matched else 0
        dist = (nearest[0] / atr_value) if nearest and atr_value > 0 else np.nan
        return matched is not None, touches, dist

    def struct_stop_for(self, direction: str, entry: float, atr_value: float, s1h: pd.Series,
                        s4h: pd.Series) -> tuple[float, float, str]:
        candidates = []
        keys = ("protected_low", "last_low") if direction == "long" else ("protected_high", "last_high")
        for tf, row in (("1H", s1h), ("4H", s4h)):
            for key in keys:
                value = row.get(key, np.nan)
                if value is None or (isinstance(value, float) and np.isnan(value)): continue

                price = float(value)
                if direction == "long" and price < entry:
                    candidates.append((tf, price))
                elif direction == "short" and price > entry:
                    candidates.append((tf, price))

        if direction == "long":
            candidates.sort(key=lambda c: entry - c[1])
        else:
            candidates.sort(key=lambda c: c[1] - entry)

        for tf, price in candidates:
            stop = price - ATR_BUFFER * atr_value if direction == "long" else price + ATR_BUFFER * atr_value
            sl_atr = abs(entry - stop) / atr_value if atr_value > 0 else np.nan
            if MIN_SL_ATR <= sl_atr <= MAX_SL_ATR: return stop, sl_atr, tf

        return np.nan, np.nan, ""

    def process_instrument(self, instrument: str) -> pd.DataFrame:
        frames = self.context.builder.build(instrument)
        if frames["1h"].empty or frames["4h"].empty: return pd.DataFrame()

        c4 = frames["4h"]
        if len(c4) < WARMUP + 5: return pd.DataFrame()

        rows = self._tag_candidates(instrument, frames)
        df = pd.DataFrame(rows)
        if df.empty: return df

        return self._score_outcomes(df, c4)

    def _tag_candidates(self, instrument: str, frames: dict) -> list[dict]:
        c4, h1 = frames["4h"], frames["1h"]
        times = c4.index
        o, hi = c4["Open"].to_numpy(), c4["High"].to_numpy()
        lo, cl = c4["Low"].to_numpy(), c4["Close"].to_numpy()
        atr_values = atr(c4).to_numpy()

        # atr terciles per instrument for the regime tag
        finite_atr = atr_values[np.isfinite(atr_values)]
        q1, q2 = (np.quantile(finite_atr, [1 / 3, 2 / 3]) if len(finite_atr) else (np.nan, np.nan))

        sw = self.asof_before(times, frames["states"]["W"])
        sd = self.asof_before(times, frames["states"]["D"])
        s4 = self.asof_before(times, frames["states"]["4H"])
        s1 = self.asof_before(times, frames["states"]["1H"])
        h1_idx = h1.index
        h1_open, h1_high = h1["Open"].to_numpy(), h1["High"].to_numpy()
        h1_low, h1_close = h1["Low"].to_numpy(), h1["Close"].to_numpy()

        rows = []
        for i in range(WARMUP, len(c4) - 2):
            a = atr_values[i]
            if not np.isfinite(a) or a <= 0: continue

            t = times[i]
            candle = c4.iloc[i]
            entry = o[i + 2]
            state_w = str(sw["state"].iloc[i]) if "state" in sw else "neutral"
            state_d = str(sd["state"].iloc[i]) if "state" in sd else "neutral"
            state_4 = str(s4["state"].iloc[i]) if "state" in s4 else "neutral"
            agree_top = {"long": 0, "short": 0}
            for state in (state_w, state_d, state_4):
                if state == "bullish":
                    agree_top["long"] += 1
                elif state == "bearish":
                    agree_top["short"] += 1

            aois = self.v3.corner_aois(frames, t, float(candle.Close), a, LOOKBACK_PIVOTS, CLUSTER_TOL_ATR)

            # the 1h window of the next bar, [open i+1, open i+2), is causal for an entry at i+2
            w_lo = np.searchsorted(h1_idx, times[i + 1], side="left")
            w_hi = np.searchsorted(h1_idx, times[i + 2], side="left")
            window_close = h1_close[slice(w_lo, w_hi)]
            regime = "mid"
            if np.isfinite(q1):
                regime = "low" if a <= q1 else ("high" if a > q2 else "mid")

            for direction in ("long", "short"):
                trigger = tier1_from_values(o[i - 1], cl[i - 1], o[i], hi[i], lo[i], cl[i], direction) or ""
                latest_m, latest_touches, latest_dist = self.at_aoi(aois, candle, direction, a, "latest_corner")
                cluster_m, cluster_touches, _ = self.at_aoi(aois, candle, direction, a, "corner_cluster")

                if direction == "long":
                    h1_close_confirm = bool((window_close > float(candle.High)).any()) if window_close.size else False
                else:
                    h1_close_confirm = bool((window_close < float(candle.Low)).any()) if window_close.size else False
                h1_pattern = bool(w_hi - w_lo >= 2) and any(
                    tier1_from_values(h1_open[k - 1], h1_close[k - 1], h1_open[k], h1_high[k], h1_low[k],
                                      h1_close[k], direction)
                    for k in range(w_lo + 1, w_hi)
                )

                stop_b, sl_atr, stop_tf = self.struct_stop_for(direction, entry, a, s1.iloc[i], s4.iloc[i])
                target_ok, rr_planned, target_b = False, np.nan, np.nan
                if np.isfinite(stop_b):
                    risk = abs(entry - stop_b)
                    target = self.v3.find_target_aoi(aois, direction, entry, risk, MIN_RR, MAX_RR)
                    if target:
                        target_ok = True
                        target_b = float(target.price)
                        rr_planned = abs(target_b - entry) / risk

                rows.append({
                    "instrument": instrument, "dir": direction, "time": t.isoformat(), "year": t.year,
                    "hour": int(t.hour), "dow": int(t.dayofweek), "entry": entry, "atr": a, "regime": regime,
                    "state_w": state_w, "state_d": state_d, "state_4h": state_4,
                    "bias2": agree_top[direction] >= 2,
                    "bias3": agree_top[direction] == 3,
                    "d4": agrees(state_d, direction) and agrees(state_4, direction),
                    "trigger": bool(trigger),
                    "trig_type": trigger,
                    "latest_aoi": latest_m,
                    "cluster_aoi": cluster_m and cluster_touches >= 2,
                    "h1_close": h1_close_confirm,
                    "h1_pattern": h1_pattern,
                    "struct_stop": bool(np.isfinite(stop_b)),
                    "target_ok": target_ok,
                    "session": 8 <= int(t.hour) <= 20,
                    "aoi_touches": latest_touches,
                    "dist_aoi_atr": round(float(latest_dist), 3) if np.isfinite(latest_dist) else np.nan,
                    "sl_atr": round(float(sl_atr), 3) if np.isfinite(sl_atr) else np.nan,
                    "stop_tf": stop_tf,
                    "rr_planned": round(float(rr_planned), 3) if np.isfinite(rr_planned) else np.nan,
                    "_stop_b": stop_b, "_tgt_b": target_b, "_i": i,
                })

        return rows

    def _score_outcomes(self, df: pd.DataFrame, c4: pd.DataFrame) -> pd.DataFrame:
        n = len(c4)
        hi, lo, cl = c4["High"].to_numpy(), c4["Low"].to_numpy(), c4["Close"].to_numpy()
        df = df.reset_index(drop=True)
        for column in LENS_A_TARGETS:
            df[column] = np.nan
        df["b_R"] = np.nan

        for direction in ("long", "short"):
            mask = (df["dir"] == direction).to_numpy()
            if not mask.any(): continue

            subset = df[mask]
            bars = subset["_i"].to_numpy()
            entries = subset["entry"].to_numpy()
            atrs = subset["atr"].to_numpy()

            # per-bar arrays aligned to the 4h series so barrier_r can scan forward
            entry_full = np.full(n, np.nan)
            stop_a, stop_b, target_b = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
            targets_a = {column: np.full(n, np.nan) for column in LENS_A_TARGETS}
            valid_a, valid_b = np.zeros(n, bool), np.zeros(n, bool)
            sign = 1.0 if direction == "long" else -1.0
            for row_pos, bar in enumerate(bars):
                e, av = entries[row_pos], atrs[row_pos]
                entry_full[bar] = e
                stop_a[bar] = e - sign * av
                for column, rr in LENS_A_TARGETS.items():
                    targets_a[column][bar] = e + sign * rr * av
                valid_a[bar] = True

                sb, tb = subset["_stop_b"].iloc[row_pos], subset["_tgt_b"].iloc[row_pos]
                if np.isfinite(sb) and np.isfinite(tb):
                    stop_b[bar], target_b[bar], valid_b[bar] = sb, tb, True

            for column in LENS_A_TARGETS:
                df.loc[mask, column] = barrier_r(direction, entry_full, stop_a, targets_a[column], hi, lo, cl,
                                                 valid_a)[bars]
            df.loc[mask, "b_R"] = barrier_r(direction, entry_full, stop_b, target_b, hi, lo, cl, valid_b)[bars]

        df["b_valid"] = np.isfinite(df["b_R"])
        df["b_rr"] = df["rr_planned"]
        return df.drop(columns=["_stop_b", "_tgt_b", "_i", "entry"])

