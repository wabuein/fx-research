from __future__ import annotations

import pandas as pd

from fxresearch.clock.broker_clock import BrokerClock
from fxresearch.data.dukascopy import DukascopyHandler
from fxresearch.structure.market_structure import StructureHandler

ALL_STATE_KEYS = ("W", "D", "4H", "1H")


class FrameBuilder:

    def __init__(self, data: DukascopyHandler, clock: BrokerClock, structure: StructureHandler) -> None:
        self.data = data
        self.clock = clock
        self.structure = structure
        self.pivots = structure.pivots

    def build(self, instrument: str) -> dict:
        return self.from_h1(self.data.load(instrument, "h1"))

    def from_h1(self, h1_utc: pd.DataFrame, state_keys: tuple[str, ...] | None = None) -> dict:
        # the backtest and the live bot both come through here, so they see identical broker frames
        frames = self.clock.build_frames(h1_utc)
        if frames["1h"].empty: return frames

        frames["states"] = self._build_states(frames, set(state_keys or ALL_STATE_KEYS))
        frames["pivots"] = {
            "W": self.pivots.find_alternating(frames["1wk"], 1, 1),
            "D": self.pivots.find_alternating(frames["1d"], 2, 2),
        }
        return frames

    def _build_states(self, frames: dict, wanted: set[str]) -> dict[str, pd.DataFrame]:
        states = {}

        if "W" in wanted: states["W"] = self.structure.build_timeline(frames["1wk"], 1, 1)
        if "D" in wanted: states["D"] = self.structure.build_timeline(frames["1d"], 2, 2)
        if "4H" in wanted: states["4H"] = self.structure.build_timeline(frames["4h"], 2, 2)
        if "1H" in wanted: states["1H"] = self.structure.build_timeline(frames["1h"], 2, 2)

        return states

