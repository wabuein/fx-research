from __future__ import annotations

import pytest

from fxresearch.context import ResearchContext
from fxresearch.data.instruments import KEEP12
from fxresearch.strategies.edge import EdgeFrames
from fxresearch.structure.pivots import CONFIRM_AT_OPEN


@pytest.fixture(scope="session")
def context() -> ResearchContext:
    return ResearchContext()


@pytest.fixture(scope="session")
def keep12_frames(context: ResearchContext) -> list[EdgeFrames]:
    return context.edge_frames_for(KEEP12)


@pytest.fixture(scope="session")
def leaky_keep12_frames() -> list[EdgeFrames]:
    return ResearchContext(confirm_at=CONFIRM_AT_OPEN).edge_frames_for(KEEP12)
