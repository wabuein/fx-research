from __future__ import annotations

from pathlib import Path

from fxresearch.analysis.report import ReportWriter, announce, write_rows
from fxresearch.engine.metrics import SPLIT_YEAR, in_sample, measure, out_of_sample
from fxresearch.paths import REPORTS_DIR
from fxresearch.strategies.edge import EdgeFrames, EdgeStrategy, EdgeTrade

COST_MULTS = (0.0, 0.5, 1.0, 2.0)
TARGET_SWEEP = (1.5, 1.75, 2.0, 2.25, 2.5)
STOP_SWEEP = (0.75, 1.0, 1.25, 1.5)
TOLERANCE_SWEEP = (0.5, 0.75, 1.0, 1.5)
BIAS_SWEEP = ("d4", "bias2", "bias3")
MIN_WHITELIST_TRADES = 5


def write_edge_trades(trades: list[EdgeTrade], tag: str, reports_dir: Path = REPORTS_DIR) -> None:
    path = reports_dir / f"edge_trades_{tag}.csv"
    write_rows(path, [trade.to_row() for trade in trades], "instrument")
    announce(path)


class EdgeGauntlet:

    def __init__(self, strategy: EdgeStrategy, frames_list: list[EdgeFrames], reports_dir: Path = REPORTS_DIR) -> None:
        self.reports_dir = reports_dir

        self.strategy = strategy
        self.frames_list = frames_list

        self.report = ReportWriter()

    def run(self) -> None:
        trades = self.strategy.run_all(self.frames_list, 1.0)

        self._header(trades)
        self._headline(trades)
        self._cost_sensitivity()
        self._per_year(trades)
        rows = self._per_instrument(trades)
        self._whitelist(trades, rows)
        self._sweeps()

        path = self.reports_dir / "edge_gauntlet.md"
        self.report.save(path)
        print()
        announce(path)
        write_edge_trades(trades, "edge_base", self.reports_dir)

    def _header(self, trades: list[EdgeTrade]) -> None:
        config = self.strategy.config
        years = sorted({trade.year for trade in trades})

        self.report.out(f"# Edge strategy gauntlet: d4 bias + fresh corner AOI, target {config.target_rr}R, "
                        f"stop {config.stop_atr}xATR, AOI tol {config.aoi_tol}xATR")
        self.report.out(f"Entry: +{config.entry_offset} 4H bar open after signal. One position/instrument at a time. "
                        f"Net of modeled cost.")
        self.report.out(f"Years {years[0]}-{years[-1]} | {len(trades)} trades "
                        f"(~{len(trades) / max(1, len(years)):.0f}/yr) | IS<{SPLIT_YEAR}={len(in_sample(trades))} "
                        f"OOS>={SPLIT_YEAR}={len(out_of_sample(trades))}")
        self.report.out("")

    def _headline(self, trades: list[EdgeTrade]) -> None:
        self.report.out("## Headline (1x modeled cost)")
        self.report.out(f"  full       {measure(trades).describe()}")
        self.report.out(f"  in-sample  {measure(in_sample(trades)).describe()}")
        self.report.out(f"  out-sample {measure(out_of_sample(trades)).describe()}")
        self.report.out("")

    def _cost_sensitivity(self) -> None:
        self.report.out("## Cost sensitivity (net), full / IS / OOS")

        for mult in COST_MULTS:
            trades = self.strategy.run_all(self.frames_list, mult)
            full, is_m, oos_m = measure(trades), measure(in_sample(trades)), measure(out_of_sample(trades))
            label = "0x(gross)" if mult == 0 else f"{mult}x"
            self.report.out(f"  {label:<9} full avg={full.avg:+.4f}  net={full.net:>6}R | "
                            f"IS avg={is_m.avg:+.4f} net={is_m.net:>6}R | "
                            f"OOS avg={oos_m.avg:+.4f} net={oos_m.net:>6}R")

        self.report.out("")

    def _per_year(self, trades: list[EdgeTrade]) -> None:
        self.report.out("## Per year (net, 1x)")

        for year in sorted({trade.year for trade in trades}):
            m = measure([trade for trade in trades if trade.year == year])
            flag = "" if m.net > 0 else "  <-"
            self.report.out(f"  {year}  n={m.n:>3}  win={m.win_pct:>4}%  net={m.net:>6}R  avg={m.avg:>+.4f}{flag}")

        self.report.out("")

    def _per_instrument(self, trades: list[EdgeTrade]) -> list[tuple]:
        self.report.out("## Per instrument (net, 1x), IS vs OOS")

        rows = []
        for frames in self.frames_list:
            subset = [trade for trade in trades if trade.instrument == frames.instrument]
            rows.append((frames.instrument, measure(in_sample(subset)), measure(out_of_sample(subset)), measure(subset)))

        for instrument, is_m, oos_m, _ in sorted(rows, key=lambda row: -row[3].net):
            self.report.out(f"  {instrument:<8} IS n={is_m.n:>3} net={is_m.net:>6}R avg={is_m.avg:>+.4f} | "
                            f"OOS n={oos_m.n:>3} net={oos_m.net:>6}R avg={oos_m.avg:>+.4f}")

        self.report.out("")
        return rows

    def _whitelist(self, trades: list[EdgeTrade], rows: list[tuple]) -> None:
        # instruments chosen on in-sample results only, then judged out-of-sample
        whitelist = sorted(instrument for instrument, is_m, _, _ in rows
                           if is_m.net > 0 and is_m.n >= MIN_WHITELIST_TRADES)
        oos = out_of_sample(trades)
        whitelist_oos = [trade for trade in oos if trade.instrument in whitelist]

        self.report.out("## IS-locked whitelist (instruments IS-net-positive, >=5 IS trades), tested OOS")
        self.report.out(f"  whitelist ({len(whitelist)}): {', '.join(whitelist) if whitelist else '(none)'}")
        self.report.out(f"  all OOS        {measure(oos).describe()}")
        self.report.out(f"  whitelist OOS  {measure(whitelist_oos).describe()}")
        self.report.out("")

    def _sweeps(self) -> None:
        self.report.out("## Parameter sweeps (full-sample net avg R/trade; OOS avg in parens): plateau check")

        self.report.out("### target RR")
        for rr in TARGET_SWEEP:
            trades, oos = self._sweep_run(target_rr=rr)
            self.report.out(f"  {rr:>4}R   n={len(trades):>4}  avg={measure(trades).avg:>+.4f}  (OOS {measure(oos).avg:>+.4f})")

        self.report.out("### stop xATR")
        for stop in STOP_SWEEP:
            trades, oos = self._sweep_run(stop_atr=stop)
            self.report.out(f"  {stop:>4}    n={len(trades):>4}  avg={measure(trades).avg:>+.4f}  (OOS {measure(oos).avg:>+.4f})")

        self.report.out("### AOI tolerance xATR")
        for tol in TOLERANCE_SWEEP:
            trades, oos = self._sweep_run(aoi_tol=tol)
            self.report.out(f"  {tol:>4}    n={len(trades):>4}  avg={measure(trades).avg:>+.4f}  (OOS {measure(oos).avg:>+.4f})")

        self.report.out("### bias mode")
        for mode in BIAS_SWEEP:
            trades, oos = self._sweep_run(bias_mode=mode)
            self.report.out(f"  {mode:<6}  n={len(trades):>4}  avg={measure(trades).avg:>+.4f}  (OOS {measure(oos).avg:>+.4f})")

        self.report.out("")

    def _sweep_run(self, **changes: object) -> tuple[list[EdgeTrade], list[EdgeTrade]]:
        trades = self.strategy.with_config(**changes).run_all(self.frames_list, 1.0)
        return trades, out_of_sample(trades)

