from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fxresearch.context import ResearchContext
from fxresearch.strategies.edge import LOCKED_CONFIG, WARMUP, EdgeConfig, EdgeFrames, bias_direction, bracket
from fxresearch.structure.aoi import RESISTANCE, SUPPORT

LIVE_STATE_KEYS = ("W", "D", "4H")


@dataclass(frozen=True)
class LiveSignal:

    instrument: str
    signal_time: str
    direction: str
    atr: float
    risk: float
    risk_pips: float
    aoi_tf: str
    aoi_price: float
    target_rr: float

    def order(self, entry: float) -> dict:
        stop, target = bracket(entry, self.direction, self.risk, self.target_rr)
        return {"direction": self.direction, "entry": entry, "stop": stop,
                "target": target, "risk_price": self.risk, "risk_pips": self.risk_pips}


class LiveSignalHandler:

    def __init__(self, context: ResearchContext, config: EdgeConfig = LOCKED_CONFIG) -> None:
        self.config = config

        self.context = context
        self.strategy = context.edge_strategy(config)

    def build_frames(self, instrument: str, h1_utc: pd.DataFrame) -> EdgeFrames:
        # feed only closed h1 bars; the frames come from the same builder the backtest uses
        frames = self.context.builder.from_h1(h1_utc, state_keys=LIVE_STATE_KEYS)
        return self.context.edge_frames(instrument, frames)

    def evaluate(self, instrument: str, h1_utc: pd.DataFrame) -> LiveSignal | None:
        return self.evaluate_frames(self.build_frames(instrument, h1_utc))

    def evaluate_frames(self, frames: EdgeFrames) -> LiveSignal | None:
        if not frames.ok: return None

        # the last 4h bar is the one that just closed
        i = len(frames.c4) - 1
        if i < WARMUP: return None

        signal = self.strategy.signal_at(frames, i)
        if signal is None: return None

        return LiveSignal(
            instrument=frames.instrument,
            signal_time=frames.times[i].isoformat(),
            direction=signal.direction,
            atr=signal.atr,
            risk=signal.risk,
            risk_pips=round(signal.risk / frames.pip, 2),
            aoi_tf=signal.aoi.tf,
            aoi_price=signal.aoi.price,
            target_rr=self.config.target_rr,
        )

    def state_line(self, instrument: str, h1_utc: pd.DataFrame) -> str:
        frames = self.build_frames(instrument, h1_utc)
        if not frames.ok: return f"{instrument:<8} (warming up / no data)"

        i = len(frames.c4) - 1
        bias = bias_direction(self.config.bias_mode, frames.sw[i], frames.sd[i], frames.s4[i]) or "flat"
        last = frames.times[i].strftime("%Y-%m-%d %H:%M")
        side = SUPPORT if bias == "long" else RESISTANCE if bias == "short" else None
        levels = [f"{corner.tf}:{corner.price:.5f}" for corner in frames.corners[i]
                  if side is None or corner.side == side]

        signal = self.evaluate_frames(frames)
        tag = f"  >>> SIGNAL {signal.direction.upper()} @AOI {signal.aoi_tf} {signal.aoi_price:.5f}" if signal else ""
        return (f"{instrument:<8} 4Hclose {last}  bias={bias:<5} "
                f"corners[{','.join(levels) if levels else '-'}]{tag}")

