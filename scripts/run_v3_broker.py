#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from fxresearch.analysis.report import announce, write_rows
from fxresearch.context import ResearchContext
from fxresearch.data.instruments import DUKA_SYMBOLS, parse_instruments
from fxresearch.paths import REPORTS_DIR, relative_to_root
from fxresearch.strategies.v3_4h_corner import BrokerCornerStrategy, V3Config, summarize_v3
from fxresearch.structure.candles import BULLISH_ENGULFING


def parse_hours(value: str) -> list[int]:
    return [int(item) for item in parse_instruments(value)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V3 rebuilt on broker candles with a causal 1H-close confirmation.")
    parser.add_argument("--bias-mode", choices=["strict", "two_of_three"], default="two_of_three")
    parser.add_argument("--session-start", type=int, default=8, help="broker-time hour, inclusive")
    parser.add_argument("--session-end", type=int, default=20, help="broker-time hour, inclusive")
    parser.add_argument("--exclude-hour", type=parse_hours, default=[])
    parser.add_argument("--max-hold-hours", type=int, default=72)
    parser.add_argument("--atr-buffer", type=float, default=0.25)
    parser.add_argument("--min-sl-atr", type=float, default=0.8)
    parser.add_argument("--max-sl-atr", type=float, default=2.5)
    parser.add_argument("--min-rr", type=float, default=1.25)
    parser.add_argument("--max-rr", type=float, default=2.5)
    parser.add_argument("--lookback-pivots", type=int, default=80)
    parser.add_argument("--cluster-tolerance-atr", type=float, default=0.75)
    parser.add_argument("--exclude-trigger", type=parse_instruments, default=[BULLISH_ENGULFING])
    parser.add_argument("--require-d4-agree", action="store_true")
    parser.add_argument("--stop-tf", choices=["any", "1H", "4H"], default="any")
    parser.add_argument("--instruments", type=parse_instruments, default=[],
                        help="restrict to a comma list of internal names; default = all")
    parser.add_argument("--tag", default="broker_full")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = V3Config(
        session_start=args.session_start, session_end=args.session_end, exclude_hour=tuple(args.exclude_hour),
        bias_mode=args.bias_mode, require_d4_agree=args.require_d4_agree, atr_buffer=args.atr_buffer,
        min_sl_atr=args.min_sl_atr, max_sl_atr=args.max_sl_atr, min_rr=args.min_rr, max_rr=args.max_rr,
        lookback_pivots=args.lookback_pivots, cluster_tolerance_atr=args.cluster_tolerance_atr,
        exclude_trigger=tuple(args.exclude_trigger), stop_tf=args.stop_tf, max_hold_hours=args.max_hold_hours,
    )
    context = ResearchContext()
    strategy = BrokerCornerStrategy(config, context.reader, context.aois)
    instruments = args.instruments or list(DUKA_SYMBOLS)

    print(f"[run_v3_broker] data source = Dukascopy H1 -> broker EET frames ({relative_to_root(context.data_dir)})")
    print(f"[run_v3_broker] confirmation = 1H close only | session = broker {args.session_start}-{args.session_end}h\n")

    trades = []
    fetch_log = {}
    for instrument in instruments:
        symbol = DUKA_SYMBOLS.get(instrument, instrument)
        print(f"Building {instrument} ({symbol})")
        frames = context.builder.build(instrument)
        if frames["1h"].empty:
            print(f"  (no data for {instrument}, skipped)")
            continue

        fetch_log[instrument] = {"symbol": symbol, "rows_1h": len(frames["1h"]), "rows_4h": len(frames["4h"]),
                                 "rows_1d": len(frames["1d"]), "rows_1wk": len(frames["1wk"])}
        trades.extend(strategy.simulate(instrument, symbol, frames))

    summary = {
        "parameters": vars(args),
        "data_source": "Dukascopy H1 resampled to Pepperstone EET broker frames (GMT+2/+3, 17:00-NY close, US DST)",
        "confirmation": "1H close beyond 4H trigger extreme only (1H-pattern confirmation dropped)",
        "fetch_log": fetch_log,
        "overall": summarize_v3(trades),
    }

    trades_path = REPORTS_DIR / f"v3_4h_corner_trades_{args.tag}.csv"
    summary_path = REPORTS_DIR / f"v3_4h_corner_summary_{args.tag}.json"
    write_rows(trades_path, [asdict(trade) for trade in trades], "instrument")
    summary_path.write_text(json.dumps(summary, indent=2))
    announce(trades_path)
    announce(summary_path)
    print(json.dumps(summary["overall"], indent=2))


if __name__ == "__main__":
    main()
