from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Rectangle

from fxresearch.context import ResearchContext
from fxresearch.costs.cost_model import RAW, STANDARD
from fxresearch.data.instruments import KEEP12
from fxresearch.engine.metrics import in_sample, measure, out_of_sample
from fxresearch.strategies.edge import LOCKED_CONFIG, EdgeFrames, EdgeTrade
from fxresearch.structure.pivots import CONFIRM_AT_OPEN

FONT = ["Avenir Next", "DejaVu Sans"]
GATE_COST = 1.5
SPLIT_DATE = pd.Timestamp("2022-01-01")
GRID_TARGETS = (1.5, 2.0, 2.5, 3.0)
GRID_STOPS = (1.0, 1.5, 2.0)
GRID_TOLERANCES = (0.75, 1.5)
GRID_BIAS = ("d4", "bias2")
GRID_ACCOUNTS = (STANDARD, RAW)


@dataclass(frozen=True)
class GateCell:

    target_rr: float
    stop_atr: float
    aoi_tol: float
    bias_mode: str
    account: str
    is_avg: float
    oos_avg: float


@dataclass
class DashboardData:

    causal: list[EdgeTrade]
    leaky: list[EdgeTrade]
    grid: list[GateCell]
    headline: GateCell
    leaky_headline: GateCell


class DashboardBuilder:

    def __init__(self, context: ResearchContext, instruments: list[str] = KEEP12) -> None:
        self.instruments = instruments

        self.context = context
        self.leaky_context = ResearchContext(confirm_at=CONFIRM_AT_OPEN)

    def build(self) -> DashboardData:
        print("Building causal and look-ahead frames ...", flush=True)
        causal_frames = self.context.edge_frames_for(self.instruments)
        leaky_frames = self.leaky_context.edge_frames_for(self.instruments)
        strategy = self.context.edge_strategy(LOCKED_CONFIG)

        print(f"Running the {self._grid_size()}-cell gate grid at {GATE_COST}x cost ...", flush=True)
        return DashboardData(
            causal=strategy.run_all(causal_frames, 1.0),
            leaky=strategy.run_all(leaky_frames, 1.0),
            grid=[self._cell(causal_frames, *combo) for combo in self._grid_combos()],
            headline=self._cell(causal_frames, 5.0, 1.0, 0.75, "d4", STANDARD),
            leaky_headline=self._cell(leaky_frames, 5.0, 1.0, 0.75, "d4", STANDARD),
        )

    def _grid_combos(self) -> list[tuple]:
        return list(itertools.product(GRID_TARGETS, GRID_STOPS, GRID_TOLERANCES, GRID_BIAS, GRID_ACCOUNTS))

    def _grid_size(self) -> int:
        return len(self._grid_combos())

    def _cell(self, frames: list[EdgeFrames], target_rr: float, stop_atr: float, aoi_tol: float, bias_mode: str,
              account: str) -> GateCell:
        strategy = self.context.edge_strategy(LOCKED_CONFIG, account).with_config(
            target_rr=target_rr, stop_atr=stop_atr, aoi_tol=aoi_tol, bias_mode=bias_mode)
        trades = strategy.run_all(frames, GATE_COST)
        return GateCell(target_rr, stop_atr, aoi_tol, bias_mode, account,
                        measure(in_sample(trades)).avg, measure(out_of_sample(trades)).avg)


@dataclass(frozen=True)
class Theme:

    name: str
    surface: str
    ink: str
    ink_2: str
    ink_3: str
    rule: str
    shade: str
    causal: str
    lookahead: str
    pass_zone: str
    muted_mark: str


# data colours validated per mode: navy is the causal result, bronze is look-ahead
LIGHT = Theme("light", surface="#FAF9F6", ink="#1C1C1E", ink_2="#5E5B57", ink_3="#9A968F", rule="#E4E1DB",
              shade="#F2F0EB", causal="#305892", lookahead="#A87431", pass_zone="#6C9173", muted_mark="#B9B5AD")
DARK = Theme("dark", surface="#141518", ink="#EDEBE7", ink_2="#A8A49D", ink_3="#77736D", rule="#2A2B2F",
             shade="#1A1C1F", causal="#6595D1", lookahead="#BA8743", pass_zone="#6C9173", muted_mark="#5C5A56")

TIMELINE_SIZE = (1600, 430)
RESULTS_SIZE = (1600, 660)


class ChartCanvas:

    def __init__(self, width: int, height: int, theme: Theme) -> None:
        self.width = width
        self.height = height
        self.theme = theme

        self.figure = plt.figure(figsize=(width / 100, height / 100), dpi=100, facecolor=theme.surface)
        self.overlay: Axes | None = None
        self.init()

    def init(self) -> None:
        # a pixel-coordinate layer for headings and annotations
        self.overlay = self.figure.add_axes((0, 0, 1, 1), zorder=-1)
        self.overlay.set_xlim(0, self.width)
        self.overlay.set_ylim(0, self.height)
        self.overlay.axis("off")

    def text(self, x: float, y: float, value: str, size: float, color: str, weight: str = "regular",
             ha: str = "left") -> None:
        self.overlay.text(x, y, value, fontsize=size, color=color, fontweight=weight, ha=ha, family=FONT)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.figure.savefig(path, facecolor=self.theme.surface, metadata={"Date": None})
        plt.close(self.figure)


class ReadmeFigures:

    def __init__(self, data: DashboardData, out_dir: Path) -> None:
        self.out_dir = out_dir

        self.data = data

    def save_all(self) -> list[Path]:
        matplotlib.rcParams.update({"svg.fonttype": "path", "svg.hashsalt": "fx-research",
                                    "axes.unicode_minus": False, "font.family": FONT})
        return [path for theme in (LIGHT, DARK) for path in (self.timeline(theme), self.results(theme))]

    def timeline(self, theme: Theme) -> Path:
        canvas = ChartCanvas(*TIMELINE_SIZE, theme)
        grid = self.data.grid
        passing = sum(1 for cell in grid if cell.is_avg > 0 and cell.oos_avg > 0)

        canvas.text(100, 362, "FX RESEARCH   ·   DUKASCOPY 2015 TO 2026   ·   12 PAIRS", 13.5, theme.ink_2, "medium")
        canvas.text(98, 288, "The edge that wasn't.", 40, theme.ink, "demibold")

        steps = [
            ("01", "Three strategies", "PF 0.74, 0.77, 0.85", None),
            ("02", "An edge appears", "PF 1.31, OOS 1.22, inflated", theme.lookahead),
            ("03", "Look-ahead found", "pivots read one bar early", theme.lookahead),
            ("04", "Parity proven", "3,745 bars, 0 mismatches", theme.causal),
            ("05", "Verdict", f"{passing} of {len(grid)} configs pass", theme.ink),
        ]
        xs = np.linspace(110, 1300, len(steps))
        rail_y = 170
        canvas.overlay.add_line(Line2D([100, 1500], [rail_y, rail_y], color=theme.rule, linewidth=1.2))

        for (number, title, detail, fill), x in zip(steps, xs):
            canvas.overlay.add_patch(Circle((x, rail_y), 7, facecolor=fill or theme.surface,
                                            edgecolor=fill or theme.ink_3, linewidth=1.4, zorder=3))
            canvas.text(x - 7, rail_y + 26, number, 13, theme.ink_3, "medium")
            canvas.text(x - 7, rail_y - 48, title, 19, theme.ink, "demibold")
            canvas.text(x - 7, rail_y - 76, detail, 15, theme.ink_2)

        canvas.text(100, 40, "Steps 01 to 04 from reports/.  The verdict is computed by scripts/make_figures.py.", 12,
                    theme.ink_3)
        path = self.out_dir / f"timeline-{theme.name}.svg"
        canvas.save(path)
        return path

    def results(self, theme: Theme) -> Path:
        canvas = ChartCanvas(*RESULTS_SIZE, theme)
        canvas.text(100, 600, "One bar of look-ahead", 24, theme.ink, "demibold")
        canvas.text(100, 572, "Cumulative net R, same rules and data, 1x cost", 14.5, theme.ink_2)
        canvas.text(880, 600, "The pass zone is empty", 24, theme.ink, "demibold")
        canvas.text(880, 572, f"Net R per trade, in-sample against out-of-sample, at {GATE_COST}x cost", 14.5, theme.ink_2)

        self._equity_panel(canvas.figure.add_axes((0.0625, 0.12, 0.40, 0.68)), theme)
        self._gate_panel(canvas.figure.add_axes((0.55, 0.12, 0.41, 0.68)), theme)

        path = self.out_dir / f"results-{theme.name}.svg"
        canvas.save(path)
        return path

    def _equity_panel(self, ax: Axes, theme: Theme) -> None:
        self._style_axes(ax, theme)
        causal, leaky = self._equity(self.data.causal), self._equity(self.data.leaky)
        start, end = causal.index[0], max(causal.index[-1], leaky.index[-1])
        right_edge = end + pd.Timedelta(days=640)

        ax.axvspan(SPLIT_DATE, end, color=theme.shade, linewidth=0, zorder=0)
        ax.axhline(0, color=theme.ink_3, linewidth=0.8, zorder=1)
        top = max(causal.max(), leaky.max())
        ax.text(start, top * 1.12, "In sample", color=theme.ink_2, fontsize=12)
        ax.text(SPLIT_DATE + pd.Timedelta(days=50), top * 1.12, "Out of sample", color=theme.ink_2, fontsize=12)

        for series, color, label in ((leaky, theme.lookahead, "with look-ahead"), (causal, theme.causal, "causal")):
            ax.plot(series.index, series.values, color=color, linewidth=1.7, label=label, zorder=3)
            ax.scatter([series.index[-1]], [series.values[-1]], s=30, color=color, zorder=4)
            ax.text(series.index[-1] + pd.Timedelta(days=70), series.values[-1] + top * 0.025,
                    f"{series.values[-1]:+.0f}R", color=theme.ink, fontsize=16, fontweight="demibold", va="center")
            ax.text(series.index[-1] + pd.Timedelta(days=70), series.values[-1] - top * 0.07, label,
                    color=theme.ink_2, fontsize=12, va="center")

        ax.set_xlim(start - pd.Timedelta(days=30), right_edge)
        ax.set_xticks([pd.Timestamp(f"{year}-01-01") for year in range(2016, 2027, 2)], [str(y) for y in range(2016, 2027, 2)])
        ax.set_ylim(min(causal.min(), leaky.min()) * 1.35, top * 1.22)
        self._legend(ax, theme, "lower left", [(theme.lookahead, "-", "with look-ahead"), (theme.causal, "-", "causal")])

    def _gate_panel(self, ax: Axes, theme: Theme) -> None:
        self._style_axes(ax, theme)
        grid, headline, leaky = self.data.grid, self.data.headline, self.data.leaky_headline
        best = max(grid, key=lambda cell: cell.oos_avg)
        x_lo, x_hi = min(cell.is_avg for cell in grid) - 0.025, 0.16
        y_lo, y_hi = min(cell.oos_avg for cell in grid) - 0.03, 0.085

        # the only region that counts: positive in-sample and out-of-sample
        ax.add_patch(Rectangle((0, 0), x_hi, y_hi, facecolor=theme.pass_zone, alpha=0.16, linewidth=0, zorder=0))
        passing = sum(1 for cell in grid if cell.is_avg > 0 and cell.oos_avg > 0)
        ax.text(x_hi - 0.007, y_hi - 0.014, "Pass zone", color=theme.ink, fontsize=14, fontweight="demibold",
                ha="right", va="top")
        ax.text(x_hi - 0.007, y_hi - 0.040, f"{passing} of {len(grid)} configs", color=theme.ink_2, fontsize=12.5,
                ha="right", va="top")
        ax.axhline(0, color=theme.ink_3, linewidth=0.8, zorder=1)
        ax.axvline(0, color=theme.ink_3, linewidth=0.8, zorder=1)

        ax.scatter([c.is_avg for c in grid], [c.oos_avg for c in grid], s=24, facecolors="none",
                   edgecolors=theme.muted_mark, linewidths=1.0, zorder=2)
        ax.annotate("", xy=(leaky.is_avg, leaky.oos_avg), xytext=(headline.is_avg, headline.oos_avg),
                    arrowprops={"arrowstyle": "-|>,head_length=0.5,head_width=0.25", "color": theme.lookahead,
                                "linewidth": 1.1, "shrinkA": 7, "shrinkB": 7}, zorder=3)
        ax.scatter([leaky.is_avg], [leaky.oos_avg], s=46, color=theme.lookahead, zorder=4)
        ax.scatter([headline.is_avg, best.is_avg], [headline.oos_avg, best.oos_avg], s=46, facecolors=theme.surface,
                   edgecolors=theme.ink, linewidths=1.3, zorder=4)

        for cell, label, dy in ((headline, "old headline", -0.024), (best, "best config", -0.013),
                                (leaky, "with look-ahead", -0.013)):
            ax.text(cell.is_avg + 0.008, cell.oos_avg + dy, label, color=theme.ink, fontsize=12.5, va="center")

        ax.set_xlim(x_lo, x_hi)
        ax.set_ylim(y_lo, y_hi)
        ax.set_xlabel("In sample, 2015 to 2021", color=theme.ink_2, fontsize=12.5, labelpad=10)
        ax.set_ylabel("Out of sample, 2022 to 2026", color=theme.ink_2, fontsize=12.5, labelpad=10)
        self._legend(ax, theme, "lower right", [(theme.muted_mark, "o", "config, fails the gate"),
                                                (theme.lookahead, "o", "same config with look-ahead")])

    def _equity(self, trades: list[EdgeTrade]) -> pd.Series:
        frame = pd.DataFrame({"t": pd.to_datetime([t.entry_time for t in trades]), "r": [t.r_net for t in trades]})
        frame = frame.sort_values("t", kind="stable")
        return pd.Series(frame["r"].cumsum().to_numpy(), index=frame["t"].to_numpy())

    def _style_axes(self, ax: Axes, theme: Theme) -> None:
        ax.set_facecolor("none")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(colors=theme.ink_2, labelsize=11.5, length=0, pad=8)
        ax.grid(True, axis="y", color=theme.rule, linewidth=0.8)
        ax.set_axisbelow(True)

    def _legend(self, ax: Axes, theme: Theme, loc: str, entries: list[tuple[str, str, str]]) -> None:
        handles = []
        for color, kind, label in entries:
            if kind == "-":
                handles.append(Line2D([], [], color=color, linewidth=1.7, label=label))
            elif color == theme.muted_mark:
                handles.append(Line2D([], [], linestyle="none", marker="o", markersize=6, markerfacecolor="none",
                                      markeredgecolor=color, label=label))
            else:
                handles.append(Line2D([], [], linestyle="none", marker="o", markersize=7, color=color, label=label))
        legend = ax.legend(handles=handles, loc=loc, frameon=False, fontsize=12, handlelength=1.4)
        for text in legend.get_texts():
            text.set_color(theme.ink_2)

