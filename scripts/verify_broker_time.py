#!/usr/bin/env python3
from __future__ import annotations

import sys

from fxresearch.clock.broker_clock import BrokerClock
from fxresearch.clock.verification import INSTRUMENT, BrokerClockVerifier
from fxresearch.data.dukascopy import DukascopyHandler


def main() -> None:
    h1_utc = DukascopyHandler().load(INSTRUMENT, "h1")
    print(f"{INSTRUMENT}: H1 UTC {h1_utc.index.min()} -> {h1_utc.index.max()} ({len(h1_utc)} rows)")

    sections = BrokerClockVerifier(BrokerClock(), h1_utc).run_all()
    for section in sections:
        print(f"\n{section.title}")
        for check in section.checks:
            mark = "PASS" if check.ok else "FAIL"
            print(f"  [{mark}] {check.label}" + (f"  ({check.detail})" if check.detail else ""))

    checks = [check for section in sections for check in section.checks]
    failures = sum(not check.ok for check in checks)
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed")
    if failures:
        print("VERIFICATION FAILED")
        sys.exit(1)
    print("VERIFICATION OK")


if __name__ == "__main__":
    main()
