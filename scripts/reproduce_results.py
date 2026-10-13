#!/usr/bin/env python3
from __future__ import annotations

from fxresearch.analysis.results_table import ResultsTable
from fxresearch.context import ResearchContext


def main() -> None:
    # rebuilds the headline table in the readme from the downloaded h1 data
    ResultsTable(ResearchContext()).run()


if __name__ == "__main__":
    main()
