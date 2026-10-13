#!/usr/bin/env python3
from __future__ import annotations

import sys

from fxresearch.analysis.honest_comparison import HonestComparison
from fxresearch.context import ResearchContext
from fxresearch.data.instruments import DUKA_SYMBOLS


def main() -> None:
    # the comparison reads structure state with a searchsorted lookup, same answers as the mask, much faster
    instruments = sys.argv[1:] or list(DUKA_SYMBOLS)
    HonestComparison(ResearchContext(fast_lookup=True), instruments).run()


if __name__ == "__main__":
    main()
