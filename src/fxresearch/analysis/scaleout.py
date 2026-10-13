from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fxresearch.analysis.report import ReportWriter, announce
from fxresearch.costs.cost_model import STANDARD, CostModel
from fxresearch.engine.metrics import in_sample, measure, out_of_sample
from fxresearch.paths import REPORTS_DIR
from fxresearch.strategies.edge import WARMUP, EdgeConfig, EdgeFrames, EdgeStrategy, bias_direction
from fxresearch.structure.corners import CornerHandler

BASE = dict(bias_mode="d4", aoi_tol=0.75, stop_atr=1.0, entry_offset=1, max_hold_hours=240)


@dataclass(frozen=True)
class ScaleOutConfig(EdgeConfig):

    # (rr, fraction) legs, ascending rr, fractions summing to 1
    legs: tuple[tuple[float, float], ...] = ()
    move_be: bool = True


@dataclass(frozen=True)
class ScaleOutTrade:

    instrument: str
    year: int
    entry_time: str
    direction: str
    r_gross: float
    r_net: float
    cost_r: float
    risk_pips: float
    exit_reason: str
    legs_filled: int


class ScaleOutSimulator:

    def __init__(self, config: ScaleOutConfig, costs: CostModel, corners: CornerHandler,
                 account: str = STANDARD) -> None:
        self.config = config
        self.account = account

        self.costs = costs
        self.corners = corners

    def run_all(self, frames_list: list[EdgeFrames], cost_mult: float = 1.0) -> list[ScaleOutTrade]:
        return [trade for frames in frames_list for trade in self.simulate(frames, cost_mult)]

    def simulate(self, frames: EdgeFrames, cost_mult: float = 1.0) -> list[ScaleOutTrade]:
        if not frames.ok: return []

        trades: list[ScaleOutTrade] = []
        last_exit = None
        offset = self.config.entry_offset

        for i in range(WARMUP, len(frames.times) - offset - 1):
            if last_exit is not None and frames.times[i] <= last_exit: continue

            a = frames.atr[i]
            if not np.isfinite(a) or a <= 0: continue

            direction = bias_direction(self.config.bias_mode, frames.sw[i], frames.sd[i], frames.s4[i])
            if not direction: continue

            match = self.corners.react_at(frames.corners[i], float(frames.lo[i]), float(frames.hi[i]),
                                          float(frames.cl[i]), direction, a, self.config.aoi_tol)
            if match is None: continue

            risk = self.config.stop_atr * a
            if risk <= 0: continue

            trade, exit_index = self._manage(frames, i, i + offset, direction, risk, cost_mult)
            trades.append(trade)
            last_exit = frames.times[exit_index]

        return trades

    def _manage(self, frames: EdgeFrames, i: int, entry_index: int, direction: str, risk: float,
                cost_mult: float) -> tuple[ScaleOutTrade, int]:
        times, hi, lo, cl = frames.times, frames.hi, frames.lo, frames.cl
        legs = self.config.legs
        entry = float(frames.o[entry_index])
        sign = 1.0 if direction == "long" else -1.0
        stop = entry - risk if direction == "long" else entry + risk
        deadline = times[entry_index] + pd.Timedelta(hours=self.config.max_hold_hours)

        realized, remaining, leg_index = 0.0, 1.0, 0
        exited, exit_index, reason = False, entry_index, "open"

        for j in range(entry_index, len(times)):
            if times[j] > deadline:
                last = max(entry_index, j - 1)
                realized += remaining * (cl[last] - entry) / risk * sign
                remaining, exited, exit_index, reason = 0.0, True, last, "time_exit"
                break

            # the stop is checked before any target on each bar, the conservative order
            stop_hit = (lo[j] <= stop) if direction == "long" else (hi[j] >= stop)
            if stop_hit:
                realized += remaining * (stop - entry) / risk * sign
                reason = "be_stop" if (leg_index >= 1 and self.config.move_be) else "stop"
                remaining, exited, exit_index = 0.0, True, j
                break

            while leg_index < len(legs):
                rr, fraction = legs[leg_index]
                target = entry + sign * rr * risk
                hit = (hi[j] >= target) if direction == "long" else (lo[j] <= target)
                if not hit: break

                realized += fraction * rr
                remaining -= fraction
                leg_index += 1
                if self.config.move_be:
                    stop = entry
                if remaining <= 1e-9:
                    exited, exit_index, reason = True, j, "targets"
                    break

            if exited: break

        if not exited:
            realized += remaining * (cl[-1] - entry) / risk * sign
            exit_index, reason = len(times) - 1, "end"

        risk_pips = risk / frames.pip
        cost = self.costs.cost_r(frames.instrument, risk_pips, cost_mult, self.account)
        trade = ScaleOutTrade(
            instrument=frames.instrument, year=int(times[i].year), entry_time=times[entry_index].isoformat(),
            direction=direction, r_gross=round(realized, 4), r_net=round(realized - cost, 4),
            cost_r=round(cost, 4), risk_pips=round(risk_pips, 2), exit_reason=reason, legs_filled=leg_index,
        )
        return trade, exit_index


class ScaleOutStudy:

    def __init__(self, edge: EdgeStrategy, frames_list: list[EdgeFrames], reports_dir: Path = REPORTS_DIR) -> None:
        self.reports_dir = reports_dir

        self.edge = edge
        self.frames_list = frames_list

        self.report = ReportWriter()

    def simulator(self, legs: tuple[tuple[float, float], ...], move_be: bool) -> ScaleOutSimulator:
        config = ScaleOutConfig(**BASE, legs=legs, move_be=move_be)
        return ScaleOutSimulator(config, self.edge.costs, self.edge.corners, self.edge.account)

    def run(self) -> None:
        out = self.report.out
        variants = [
            ("single 2R (baseline)", self.edge.with_config(**BASE, target_rr=2.0)),
            ("50% @1R + 50% run 3R, +BE", self.simulator(((1.0, 0.5), (3.0, 0.5)), True)),
            ("50% @1R + 50% run 2R, +BE", self.simulator(((1.0, 0.5), (2.0, 0.5)), True)),
            ("50% @0.5R + 50% run 3R, +BE", self.simulator(((0.5, 0.5), (3.0, 0.5)), True)),
            ("67% @0.5R + 33% run 3R, +BE", self.simulator(((0.5, 0.67), (3.0, 0.33)), True)),
            ("50% @1R + 50% run 3R, NO BE", self.simulator(((1.0, 0.5), (3.0, 0.5)), False)),
        ]

        out("# Edge scale-out study: d4 bias + fresh corner, 1xATR stop, net of 1x cost")
        out("'win' = trade closes net R > 0 (a banked partial then breakeven scratch counts).")
        out(f"{'config':<32}{'n':>5}{'win%':>7}{'netR/t':>9}{'totR':>7}{'PF':>6}{'maxDD':>7}{'OOS win%':>9}"
            f"{'OOS netR/t':>11}")
        for label, simulator in variants:
            trades = simulator.run_all(self.frames_list, 1.0)
            m, mo = measure(trades), measure(out_of_sample(trades))
            pf = "inf" if m.pf == float("inf") else f"{m.pf:.2f}"
            out(f"{label:<32}{m.n:>5}{m.win_pct:>7}{m.avg:>+9.4f}{m.net:>7.0f}{pf:>6}"
                f"{m.max_dd:>7.1f}{mo.win_pct:>9}{mo.avg:>+11.4f}")

        out("")
        out("Read: scale-out lifts win% a lot (banked partials) and cuts drawdown, while net")
        out("expectancy/trade stays in the same thin band as single-target. It reshapes the")
        out("experience, it does not manufacture an edge. Total R can drop because half the")
        out("size comes off before the runner pays.")

        out("\n## Detail: 67% @0.5R + 33% run 3R, +BE")
        trades = self.simulator(((0.5, 0.67), (3.0, 0.33)), True).run_all(self.frames_list, 1.0)
        out(f"  exit reasons: {dict(Counter(trade.exit_reason for trade in trades))}")
        out(f"  full  {measure(trades).describe()}")
        out(f"  IS    {measure(in_sample(trades)).describe()}")
        out(f"  OOS   {measure(out_of_sample(trades)).describe()}")

        path = self.reports_dir / "edge_scaleout.md"
        self.report.save(path)
        print()
        announce(path)

