from __future__ import annotations

from pathlib import Path

from fxresearch.clock.broker_clock import BrokerClock
from fxresearch.costs.cost_model import STANDARD, CostModel
from fxresearch.data.dukascopy import DukascopyHandler
from fxresearch.engine.frames import FrameBuilder
from fxresearch.paths import DATA_DIR
from fxresearch.strategies.edge import EdgeConfig, EdgeFrames, EdgeStrategy
from fxresearch.structure.aoi import AoiHandler
from fxresearch.structure.corners import CornerHandler
from fxresearch.structure.market_structure import StructureHandler, StructureReader
from fxresearch.structure.pivots import CONFIRM_AT_CLOSE, PivotHandler


class ResearchContext:

    def __init__(self, data_dir: Path = DATA_DIR, confirm_at: str = CONFIRM_AT_CLOSE,
                 fast_lookup: bool = False) -> None:
        self.data_dir = data_dir
        self.confirm_at = confirm_at
        self.fast_lookup = fast_lookup

        self.data: DukascopyHandler | None = None
        self.clock: BrokerClock | None = None
        self.pivots: PivotHandler | None = None
        self.structure: StructureHandler | None = None
        self.builder: FrameBuilder | None = None
        self.reader: StructureReader | None = None
        self.aois: AoiHandler | None = None
        self.corners: CornerHandler | None = None
        self.costs: CostModel | None = None
        self.init()

    def init(self) -> None:
        self.data = DukascopyHandler(self.data_dir)
        self.clock = BrokerClock()
        self.pivots = PivotHandler(self.confirm_at)
        self.structure = StructureHandler(self.pivots)
        self.builder = FrameBuilder(self.data, self.clock, self.structure)
        self.reader = StructureReader(self.fast_lookup)
        self.aois = AoiHandler()
        self.corners = CornerHandler()
        self.costs = CostModel()

    def edge_frames(self, instrument: str, frames: dict | None = None) -> EdgeFrames:
        built = self.builder.build(instrument) if frames is None else frames
        return EdgeFrames(instrument, built, self.reader, self.corners)

    def edge_frames_for(self, instruments: list[str]) -> list[EdgeFrames]:
        loaded = [self.edge_frames(instrument) for instrument in instruments]
        return [frames for frames in loaded if frames.ok]

    def edge_strategy(self, config: EdgeConfig, account: str = STANDARD) -> EdgeStrategy:
        return EdgeStrategy(config, self.costs, self.corners, account)

