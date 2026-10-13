#!/usr/bin/env python3
from __future__ import annotations

import argparse

from fxresearch.analysis.gauntlet import EdgeGauntlet, write_edge_trades
from fxresearch.context import ResearchContext
from fxresearch.costs.cost_model import RAW, STANDARD
from fxresearch.data.instruments import DUKA_SYMBOLS, parse_instruments
from fxresearch.engine.metrics import in_sample, measure, out_of_sample
from fxresearch.strategies.edge import EdgeConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="4H fresh-corner strategy: single run or the full IS/OOS gauntlet.")
    parser.add_argument("--bias-mode", choices=["d4", "bias2", "bias3"], default="d4")
    parser.add_argument("--aoi-tol", type=float, default=0.75, help="fresh-corner reaction tolerance in ATR")
    parser.add_argument("--stop-atr", type=float, default=1.0, help="stop distance in ATR")
    parser.add_argument("--target-rr", type=float, default=2.0, help="target as multiple of risk")
    parser.add_argument("--entry-offset", type=int, default=1, help="enter this many 4H bars after the signal bar")
    parser.add_argument("--max-hold-hours", type=int, default=240)
    parser.add_argument("--instruments", type=parse_instruments, default=[])
    parser.add_argument("--cost-mult", type=float, default=1.0)
    parser.add_argument("--account", choices=[STANDARD, RAW], default=STANDARD)
    parser.add_argument("--gauntlet", action="store_true")
    parser.add_argument("--tag", default="edge_base")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = EdgeConfig(bias_mode=args.bias_mode, aoi_tol=args.aoi_tol, stop_atr=args.stop_atr,
                        target_rr=args.target_rr, entry_offset=args.entry_offset,
                        max_hold_hours=args.max_hold_hours)
    instruments = args.instruments or list(DUKA_SYMBOLS)

    context = ResearchContext()
    strategy = context.edge_strategy(config, args.account)

    print(f"Building frames for {len(instruments)} instruments ...", flush=True)
    frames_list = context.edge_frames_for(instruments)
    print(f"  {len(frames_list)} ready\n", flush=True)

    if args.gauntlet:
        EdgeGauntlet(strategy, frames_list).run()
        return

    trades = strategy.run_all(frames_list, args.cost_mult)
    print(f"## {args.bias_mode} + fresh-corner AOI, {args.target_rr}R / {args.stop_atr}xATR stop")
    print(f"  full       {measure(trades).describe()}")
    print(f"  in-sample  {measure(in_sample(trades)).describe()}")
    print(f"  out-sample {measure(out_of_sample(trades)).describe()}")
    if trades:
        write_edge_trades(trades, args.tag)


if __name__ == "__main__":
    main()
