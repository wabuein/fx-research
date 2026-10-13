#!/usr/bin/env python3
from __future__ import annotations

import sys

from fxresearch.analysis.confluence_lab import ConfluenceLab
from fxresearch.context import ResearchContext
from fxresearch.data.instruments import DUKA_SYMBOLS


def main() -> None:
    # tag every 4h bar, long and short, with the confluences present; ranking lives in confluence_analyze.py
    ConfluenceLab(ResearchContext()).run(sys.argv[1:] or list(DUKA_SYMBOLS))


if __name__ == "__main__":
    main()
