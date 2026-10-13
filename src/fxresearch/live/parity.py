from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fxresearch.context import ResearchContext
from fxresearch.engine.simulator import simulate_trade
from fxresearch.live.signal import LiveSignalHandler
from fxresearch.strategies.edge import WARMUP, EdgeFrames, bracket

MAX_EXAMPLES = 6
FOUR_HOURS = pd.Timedelta(hours=4)


@dataclass
class ParityResult:

    instrument: str
    ok: bool
    reason: str = ""
    checked: int = 0
    mismatch: int = 0
    sig_live: int = 0
    sig_truth: int = 0
    n_trades: int = 0
    seq_ok: bool = False
    examples: list[tuple] = field(default_factory=list)

    def passed(self) -> bool:
        return self.ok and self.mismatch == 0 and self.seq_ok


@dataclass(frozen=True)
class ReplayedTrade:

    signal_time: str
    direction: str
    stop: float
    target: float


class ParityGate:

    def __init__(self, context: ResearchContext, live: LiveSignalHandler) -> None:
        self.context = context
        self.live = live
        self.strategy = live.strategy

    def check_instrument(self, instrument: str, n_checks: int) -> ParityResult:
        h1 = self.context.data.load(instrument, "h1")
        full = self.context.edge_frames(instrument)
        if not full.ok: return ParityResult(instrument, False, "no/short data")

        truth = self.full_signal_map(full)
        result = ParityResult(instrument, True)
        broker_index = self.context.clock.to_broker_time(h1).index

        # truncate the feed at each tested bar's close and rebuild from scratch, exactly what the bot sees
        for i in self._bars_to_test(full, truth, n_checks):
            cutoff = full.times[i] + FOUR_HOURS
            live_frames = self.live.build_frames(instrument, h1[np.asarray(broker_index < cutoff)])
            self._compare_bar(result, full, truth, live_frames, i)

        backtest = self.strategy.simulate(full)
        replayed = self.reconstruct_trades(full)
        result.n_trades = len(backtest)
        result.seq_ok = len(backtest) == len(replayed) and all(
            a.signal_time == b.signal_time and a.direction == b.direction
            and abs(a.stop - b.stop) < 1e-9 and abs(a.target - b.target) < 1e-9
            for a, b in zip(backtest, replayed)
        )
        return result

    def full_signal_map(self, frames: EdgeFrames) -> dict:
        truth = {}

        for i in range(WARMUP, len(frames.c4)):
            signal = self.strategy.signal_at(frames, i)
            if signal is not None:
                truth[frames.times[i]] = (signal.direction, round(signal.risk, 8), signal.aoi.tf,
                                          round(signal.aoi.price, 8))

        return truth

    def reconstruct_trades(self, frames: EdgeFrames) -> list[ReplayedTrade]:
        # the way the bot trades: signal at the close, enter at the next open, one position at a time
        config = self.strategy.config
        offset = config.entry_offset
        replayed: list[ReplayedTrade] = []
        last_exit = None

        for i in range(WARMUP, len(frames.c4) - offset - 1):
            if last_exit is not None and frames.times[i] <= last_exit: continue

            signal = self.strategy.signal_at(frames, i)
            if signal is None: continue

            entry = float(frames.o[i + offset])
            stop, target = bracket(entry, signal.direction, signal.risk, config.target_rr)
            outcome = simulate_trade(frames.c4, i + offset, signal.direction, entry, stop, target, config.max_hold_hours)
            replayed.append(ReplayedTrade(frames.times[i].isoformat(), signal.direction, round(stop, 6), round(target, 6)))
            last_exit = outcome.time

        return replayed

    def _bars_to_test(self, full: EdgeFrames, truth: dict, n_checks: int) -> list[int]:
        # a recent window plus every historical signal bar, so the signal path itself is exercised
        n = len(full.c4)
        positions = {full.times[i]: i for i in range(n)}
        recent = set(range(max(WARMUP, n - n_checks), n - 1))
        signal_bars = {positions[t] for t in truth if positions.get(t, n) < n - 1}
        return sorted(recent | signal_bars)

    def _compare_bar(self, result: ParityResult, full: EdgeFrames, truth: dict, live_frames: EdgeFrames,
                     i: int) -> None:
        result.checked += 1
        if not live_frames.ok or live_frames.times[-1] != full.times[i]:
            result.examples.append((full.times[i], "BOUNDARY", live_frames.ok and str(live_frames.times[-1])))
            result.mismatch += 1
            return

        live_signal = self.live.evaluate_frames(live_frames)
        expected = truth.get(full.times[i])
        actual = None
        if live_signal is not None:
            result.sig_live += 1
            actual = (live_signal.direction, round(live_signal.risk, 8), live_signal.aoi_tf,
                      round(live_signal.aoi_price, 8))
        if expected is not None:
            result.sig_truth += 1

        if actual != expected:
            result.mismatch += 1
            if len(result.examples) < MAX_EXAMPLES:
                result.examples.append((str(full.times[i]), f"live={actual}", f"truth={expected}"))

