#!/usr/bin/env python3
from __future__ import annotations

import argparse

from fxresearch.context import ResearchContext
from fxresearch.data.instruments import KEEP12, parse_instruments
from fxresearch.live.parity import ParityGate
from fxresearch.live.signal import LiveSignalHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prove the live signal path reproduces the backtest bar for bar.")
    parser.add_argument("instruments", nargs="?", default="EURUSD,AUDJPY,GBPUSD", help="comma list or 'all'")
    parser.add_argument("n_checks", nargs="?", type=int, default=80, help="recent bars per instrument")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    instruments = KEEP12 if args.instruments == "all" else parse_instruments(args.instruments)

    context = ResearchContext()
    gate = ParityGate(context, LiveSignalHandler(context))
    print(f"Replay parity: {len(instruments)} pairs, last {args.n_checks} bars each, config d4/1xATR/5R\n")

    total_checked = total_mismatch = 0
    all_sequential = True
    for instrument in instruments:
        result = gate.check_instrument(instrument, args.n_checks)
        if not result.ok:
            print(f"  {instrument:<8} SKIP ({result.reason})")
            continue

        total_checked += result.checked
        total_mismatch += result.mismatch
        all_sequential = all_sequential and result.seq_ok
        flag = "OK " if result.passed() else "FAIL"
        print(f"  {flag} {instrument:<8} checked={result.checked:>4} mismatch={result.mismatch:>3} "
              f"live_sigs={result.sig_live:>3} truth_sigs={result.sig_truth:>3} "
              f"trades={result.n_trades:>3} seq_parity={'yes' if result.seq_ok else 'NO'}")
        for example in result.examples:
            print(f"        mismatch @ {example}")

    print(f"\nTOTAL checked={total_checked} mismatch={total_mismatch} "
          f"sequential_parity={'ALL OK' if all_sequential else 'BROKEN'}")
    proven = total_mismatch == 0 and all_sequential
    print("VERDICT:", "PARITY PROVEN, live == backtest, no look-ahead" if proven
          else "PARITY FAILED, investigate before demo")


if __name__ == "__main__":
    main()
