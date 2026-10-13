#!/usr/bin/env python3
from __future__ import annotations

from fxresearch.analysis.risk import RiskModel
from fxresearch.costs.cost_model import CostModel


def main() -> None:
    # reads reports/edge_trades_edge_base.csv, so run the edge gauntlet first
    RiskModel(CostModel()).run()


if __name__ == "__main__":
    main()
