#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import date

from fxresearch.data.downloader import DukascopyDownloader
from fxresearch.data.dukascopy import DukascopyHandler
from fxresearch.data.instruments import DUKA_SYMBOLS, parse_instruments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Dukascopy OHLC (via the dukascopy-node CLI) into data/dukascopy/.")
    parser.add_argument("--from", dest="date_from", default="2015-01-01")
    parser.add_argument("--to", dest="date_to", default=date.today().isoformat())
    parser.add_argument("--instruments", default="", help="comma list of internal names; default all")
    parser.add_argument("--timeframes", default="h1,d1", help="comma list, e.g. h1,d1,m15")
    parser.add_argument("--price", default="bid", choices=["bid", "ask"], help="bid (default) or ask (-> *_ask.csv)")
    parser.add_argument("--skip-existing", action="store_true", help="skip files that already cover the range")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    instruments = parse_instruments(args.instruments) or list(DUKA_SYMBOLS)
    timeframes = parse_instruments(args.timeframes)
    unknown = [instrument for instrument in instruments if instrument not in DUKA_SYMBOLS]
    if unknown: sys.exit(f"Unknown instruments: {unknown}. Known: {list(DUKA_SYMBOLS)}")

    print(f"Dukascopy download {args.date_from} -> {args.date_to}")
    print(f"Instruments: {len(instruments)} | timeframes: {timeframes}\n")

    downloader = DukascopyDownloader(DukascopyHandler(), args.price)
    results = downloader.download_all(instruments, timeframes, args.date_from, args.date_to, args.skip_existing)
    for result in results:
        label = f"{result.instrument:<8} {result.tf:<3} {args.price} ({DUKA_SYMBOLS[result.instrument]})"
        status = "OK  " if result.ok else "FAIL"
        print(f"  [{status}] {label:<28} {result.message}")

    failures = [result for result in results if not result.ok]
    print()
    if failures:
        print(f"{len(failures)} failures:")
        for result in failures:
            print(f"  - {result.instrument}/{result.tf}: {result.message}")
        sys.exit(1)
    print("All downloads complete.")


if __name__ == "__main__":
    main()
