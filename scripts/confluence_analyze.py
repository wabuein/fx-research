#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from fxresearch.analysis.confluence_analyzer import ConfluenceAnalyzer
from fxresearch.costs.cost_model import CostModel
from fxresearch.paths import REPORTS_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank confluences from the tagged confluence_samples.csv universe.")
    parser.add_argument("--samples", default=str(REPORTS_DIR / "confluence_samples.csv"))
    parser.add_argument("--out", default=str(REPORTS_DIR / "confluence_ranking.md"))
    args = parser.parse_args()

    ConfluenceAnalyzer(CostModel(), Path(args.samples), Path(args.out)).run()


if __name__ == "__main__":
    main()
