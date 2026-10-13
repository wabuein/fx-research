from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from fxresearch.analysis.report import ReportWriter, announce
from fxresearch.analysis.scaleout import BASE, ScaleOutStudy
from fxresearch.engine.metrics import SPLIT_YEAR
from fxresearch.paths import REPORTS_DIR
from fxresearch.strategies.edge import EdgeFrames, EdgeStrategy


class MonthlyStudy:

    def __init__(self, edge: EdgeStrategy, frames_list: list[EdgeFrames], reports_dir: Path = REPORTS_DIR) -> None:
        self.reports_dir = reports_dir

        self.edge = edge.with_config(**BASE)
        self.frames_list = frames_list
        self.scaleout = ScaleOutStudy(edge, frames_list, reports_dir)

        self.report = ReportWriter()
        self.rows: list[tuple[str, dict, dict, dict]] = []

    def monthly(self, trades: list[Any], mask: str | None = None) -> dict:
        if not trades: return {}

        df = pd.DataFrame([asdict(trade) for trade in trades])
        if mask == "is": df = df[df["year"] < SPLIT_YEAR]
        if mask == "oos": df = df[df["year"] >= SPLIT_YEAR]
        if df.empty: return {}

        df["ym"] = pd.to_datetime(df["entry_time"]).dt.strftime("%Y-%m")
        by_month = df.groupby("ym")["r_net"].sum()
        return {
            "months": len(by_month),
            "pct_green": 100 * (by_month > 0).mean(),
            "avg_month": by_month.mean(),
            "median_month": by_month.median(),
            "worst_month": by_month.min(),
            "best_month": by_month.max(),
            "trades_per_month": len(df) / len(by_month),
            "total_R": df["r_net"].sum(),
        }

    def run(self) -> None:
        out = self.report.out
        out("# Optimizing the 4H edge for PROFITABLE MONTHS (net 1x cost)")
        out("Ranked by % of months in the green. Objective: most green months while total R > 0.")
        out(f"{'config':<30}{'tr/mo':>6}{'%GREEN':>8}{'IS':>6}{'OOS':>6}{'medMo':>8}{'worstMo':>9}{'totR':>7}")

        out("-- single target, trend2 (Daily+4H) --")
        for rr in (1.5, 2.0, 2.5, 3.0, 5.0):
            self._add(f"single {rr}R", self._single(target_rr=rr))
        out("-- single target, looser AOI (more trades) --")
        for tol in (1.0, 1.5):
            self._add(f"single 2R tol{tol}", self._single(target_rr=2.0, aoi_tol=tol))
        out("-- scale-out (smoother) --")
        self._add("50%@1R + run3R +BE", self._scaled(((1.0, 0.5), (3.0, 0.5))))
        self._add("50%@1R + run5R +BE", self._scaled(((1.0, 0.5), (5.0, 0.5))))
        self._add("67%@1R + run4R +BE", self._scaled(((1.0, 0.67), (4.0, 0.33))))
        self._add("50%@1.5R + run5R +BE", self._scaled(((1.5, 0.5), (5.0, 0.5))))
        out("-- trend3 (stricter, fewer trades) --")
        self._add("trend3 single 2.5R", self._single(target_rr=2.5, bias_mode="bias3"))

        out("")
        label, m, mi, mo = max(self.rows, key=lambda row: (row[1]["pct_green"], row[1]["total_R"]))
        out(f"Most green months: {label} -> {m['pct_green']:.1f}% of months green "
            f"(IS {mi['pct_green']:.0f}% / OOS {mo['pct_green']:.0f}%), "
            f"median month {m['median_month']:+.2f}R, total {m['total_R']:.0f}R")
        out("Note: a higher green-month % usually trades away total R. Pick the row whose "
            "green% you can live with while total R stays clearly positive.")

        path = self.reports_dir / "edge_monthly.md"
        self.report.save(path)
        print()
        announce(path)

    def _single(self, **changes: object) -> list[Any]:
        return self.edge.with_config(**changes).run_all(self.frames_list, 1.0)

    def _scaled(self, legs: tuple[tuple[float, float], ...]) -> list[Any]:
        return self.scaleout.simulator(legs, True).run_all(self.frames_list, 1.0)

    def _add(self, label: str, trades: list[Any]) -> None:
        m = self.monthly(trades)
        if not m: return

        mi, mo = self.monthly(trades, "is"), self.monthly(trades, "oos")
        self.rows.append((label, m, mi, mo))
        self.report.out(f"{label:<30}{m['trades_per_month']:>6.1f}{m['pct_green']:>7.1f}%"
                        f"{mi.get('pct_green', 0):>6.0f}{mo.get('pct_green', 0):>6.0f}"
                        f"{m['median_month']:>+8.2f}{m['worst_month']:>+9.1f}{m['total_R']:>7.0f}")

