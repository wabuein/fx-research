#!/usr/bin/env python3
from __future__ import annotations

import argparse

from fxresearch.analysis.timeframe import TimeframeConfig, TimeframeStudy
from fxresearch.context import ResearchContext
from fxresearch.data.instruments import DUKA_SYMBOLS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fresh-corner edge on 4H and 1H signals, reported by week.")
    parser.add_argument("--target-rr", type=float, default=5.0)
    parser.add_argument("--stop-atr", type=float, default=1.0)
    parser.add_argument("--aoi-tol", type=float, default=0.75)
    parser.add_argument("--bias-mode", choices=["trend2", "trend3"], default="trend2")
    parser.add_argument("--entry-offset", type=int, default=1)
    parser.add_argument("--max-hold-bars", type=int, default=60)
    args = parser.parse_args()

    config = TimeframeConfig(target_rr=args.target_rr, stop_atr=args.stop_atr, aoi_tol=args.aoi_tol,
                             bias_mode=args.bias_mode, entry_offset=args.entry_offset,
                             max_hold_bars=args.max_hold_bars)
    TimeframeStudy(config, ResearchContext(), list(DUKA_SYMBOLS)).run()


if __name__ == "__main__":
    main()
