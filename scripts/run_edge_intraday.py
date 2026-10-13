#!/usr/bin/env python3
from __future__ import annotations

import argparse

from fxresearch.analysis.intraday import TFS, IntradayConfig, IntradayStudy
from fxresearch.context import ResearchContext
from fxresearch.data.instruments import KEEP12, parse_instruments


def parse_session(value: str) -> list[int] | None:
    return [int(item) for item in value.split(",")] if value else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fresh-corner idea on faster signal timeframes, with cost levers.")
    parser.add_argument("--signal-tf", choices=list(TFS), default="1h")
    parser.add_argument("--instruments", type=parse_instruments, default=list(KEEP12))
    parser.add_argument("--bias-mode", default="d4")
    parser.add_argument("--aoi-source", choices=["corners", "intraday", "both"], default="corners")
    parser.add_argument("--aoi-tol", type=float, default=0.75)
    parser.add_argument("--stop-atr", type=float, default=1.0)
    parser.add_argument("--target-rr", type=float, default=5.0)
    parser.add_argument("--entry-offset", type=int, default=1)
    parser.add_argument("--max-hold-bars", type=int, default=60)
    parser.add_argument("--min-risk-pips", type=float, default=0.0)
    parser.add_argument("--vol-pct", type=float, default=0.0, help="trade only when ATR percentile >= this")
    parser.add_argument("--session", type=parse_session, default=None, help="broker hour window 'start,end' inclusive")
    parser.add_argument("--ema-trend", type=int, default=0)
    parser.add_argument("--scan", action="store_true", help="sweep the key intraday levers")
    parser.add_argument("--tag", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = IntradayConfig(
        signal_tf=args.signal_tf, instruments=args.instruments, bias_mode=args.bias_mode,
        aoi_source=args.aoi_source, aoi_tol=args.aoi_tol, stop_atr=args.stop_atr, target_rr=args.target_rr,
        entry_offset=args.entry_offset, max_hold_bars=args.max_hold_bars, min_risk_pips=args.min_risk_pips,
        vol_pct=args.vol_pct, session=args.session, ema_trend=args.ema_trend,
    )
    IntradayStudy(config, ResearchContext()).run(args.scan, args.tag)


if __name__ == "__main__":
    main()
