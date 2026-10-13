#!/usr/bin/env python3
from __future__ import annotations

from fxresearch.live.config import CTraderConfig
from fxresearch.live.ctrader_auth import CTraderAuth


def main() -> None:
    # one-shot oauth: set the app redirect uri to http://localhost:5000/ first, see docs/ctrader_setup.md
    CTraderAuth(CTraderConfig()).run()


if __name__ == "__main__":
    main()
