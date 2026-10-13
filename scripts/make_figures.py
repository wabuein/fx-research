#!/usr/bin/env python3
from __future__ import annotations

from fxresearch.analysis.figures import DashboardBuilder, ReadmeFigures
from fxresearch.context import ResearchContext
from fxresearch.paths import PROJECT_ROOT, relative_to_root


def main() -> None:
    # regenerates the readme images from the backtest engine, about five minutes
    data = DashboardBuilder(ResearchContext()).build()
    for path in ReadmeFigures(data, PROJECT_ROOT / "docs" / "img").save_all():
        print(f"Wrote {relative_to_root(path)}")


if __name__ == "__main__":
    main()
