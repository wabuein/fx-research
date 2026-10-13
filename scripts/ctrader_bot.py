#!/usr/bin/env python3
from __future__ import annotations

import argparse

from fxresearch.context import ResearchContext
from fxresearch.live.config import CTraderConfig
from fxresearch.live.ctrader_bot import CTraderHandler, load_sdk
from fxresearch.live.signal import LiveSignalHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="cTrader demo harness for the parity-tested 4H signal (dry run by default).")
    parser.add_argument("--list-accounts", action="store_true", help="print the ctidTraderAccountId list, then exit")
    args = parser.parse_args()

    config = CTraderConfig()
    sdk = load_sdk()
    CTraderHandler(config, sdk, LiveSignalHandler(ResearchContext()), list_only=args.list_accounts).run()


if __name__ == "__main__":
    main()
