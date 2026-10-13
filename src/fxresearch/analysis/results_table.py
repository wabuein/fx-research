from __future__ import annotations

from pathlib import Path
from typing import Any

from fxresearch.analysis.intraday import IntradayConfig, IntradayFrames, IntradayStrategy
from fxresearch.analysis.report import ReportWriter, announce
from fxresearch.context import ResearchContext
from fxresearch.costs.cost_model import RAW, STANDARD
from fxresearch.data.instruments import KEEP12
from fxresearch.engine.metrics import Performance, in_sample, measure, out_of_sample
from fxresearch.paths import REPORTS_DIR
from fxresearch.strategies.edge import EdgeConfig

# the bar every configuration must clear: net positive in-sample and out-of-sample at 1.5x modeled cost
GATE_COST_MULT = 1.5
FOUR_HOUR_ROWS = [
    ("4H", "d4, fresh corner, 1xATR stop, 5R (the old headline config)", EdgeConfig(target_rr=5.0, stop_atr=1.0)),
    ("4H", "d4, fresh corner, 2xATR stop, 3R (best cell found)", EdgeConfig(target_rr=3.0, stop_atr=2.0)),
]
ONE_HOUR_ROWS = [
    ("1H", "4H+1H bias, 4H/D corners, 2xATR stop, 5R", IntradayConfig(signal_tf="1h", stop_atr=2.0, target_rr=5.0)),
]
ACCOUNTS = (("Standard", STANDARD), ("Raw", RAW))


class ResultsTable:

    def __init__(self, context: ResearchContext, instruments: list[str] = KEEP12,
                 reports_dir: Path = REPORTS_DIR) -> None:
        self.instruments = instruments
        self.reports_dir = reports_dir

        self.context = context

        self.report = ReportWriter()

    def run(self) -> None:
        out = self.report.out
        out(f"# Results at the gate: {len(self.instruments)} FX pairs, 2015-2026, net of {GATE_COST_MULT}x modeled cost")
        out("")
        out("IS = 2015-2021, OOS = 2022-2026. avg is net R per trade. Gate = net positive in both IS and OOS.")
        out("")
        out("| TF | Config | Account | n | Full avg / PF | IS avg / PF | OOS avg / PF | Gate |")
        out("| --- | --- | --- | ---: | ---: | ---: | ---: | --- |")

        print("Building 4H frames ...", flush=True)
        four_hour = self.context.edge_frames_for(self.instruments)
        for tf, label, config in FOUR_HOUR_ROWS:
            for account_label, account in ACCOUNTS:
                trades = self.context.edge_strategy(config, account).run_all(four_hour, GATE_COST_MULT)
                self._row(tf, label, account_label, trades)

        print("Building 1H frames ...", flush=True)
        loaded = [IntradayFrames(instrument, "1h", self.context) for instrument in self.instruments]
        one_hour = [frames for frames in loaded if frames.ok]
        strategy = IntradayStrategy(self.context)
        for tf, label, config in ONE_HOUR_ROWS:
            for account_label, account in ACCOUNTS:
                trades = strategy.run_universe(one_hour, config, GATE_COST_MULT, account)
                self._row(tf, label, account_label, trades)

        path = self.reports_dir / "results_table.md"
        self.report.save(path)
        print()
        announce(path)

    def _row(self, tf: str, label: str, account: str, trades: list[Any]) -> None:
        full, is_m, oos_m = measure(trades), measure(in_sample(trades)), measure(out_of_sample(trades))
        self.report.out(f"| {tf} | {label} | {account} | {full.n} | {self._cell(full)} | {self._cell(is_m)} | "
                        f"{self._cell(oos_m)} | {self._gate(is_m, oos_m)} |")

    def _cell(self, m: Performance) -> str:
        return f"{m.avg:+.4f} / {m.pf:.2f}"

    def _gate(self, is_m: Performance, oos_m: Performance) -> str:
        if is_m.avg > 0 and oos_m.avg > 0: return "pass"
        if is_m.avg > 0: return "fail (OOS)"
        return "fail"

