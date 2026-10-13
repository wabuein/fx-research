#!/usr/bin/env python3
from __future__ import annotations

from fxresearch.analysis.scaleout import ScaleOutStudy
from fxresearch.context import ResearchContext
from fxresearch.data.instruments import DUKA_SYMBOLS
from fxresearch.strategies.edge import EdgeConfig


def main() -> None:
    context = ResearchContext()
    print("Building frames ...", flush=True)
    frames_list = context.edge_frames_for(list(DUKA_SYMBOLS))
    print(f"  {len(frames_list)} ready\n", flush=True)

    ScaleOutStudy(context.edge_strategy(EdgeConfig()), frames_list).run()


if __name__ == "__main__":
    main()
