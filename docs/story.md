# The full story

The README shows the result in two pictures. This page has the numbers and the reasoning behind them.

## The result

12 FX pairs, H1 Dukascopy data, 2015-01-01 to 2026-06-12. In-sample 2015 to 2021, out-of-sample 2022 to
2026. Costs at **1.5x** the measured Dukascopy spread, roughly a retail Standard account. `avg` is net
R per trade (R = the amount risked).

| TF | Config | Account | n | Full avg / PF | IS avg / PF | OOS avg / PF | Gate |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 4H | d4, fresh corner, 1xATR stop, 5R (the old headline config) | Standard | 1372 | -0.0544 / 0.94 | -0.0016 / 1.00 | -0.1372 / 0.84 | fail |
| 4H | d4, fresh corner, 1xATR stop, 5R (the old headline config) | Raw | 1372 | -0.0875 / 0.90 | -0.0345 / 0.96 | -0.1703 / 0.81 | fail |
| 4H | d4, fresh corner, 2xATR stop, 3R (best cell found) | Standard | 1127 | +0.0054 / 1.01 | +0.0504 / 1.08 | -0.0641 / 0.91 | fail (OOS) |
| 4H | d4, fresh corner, 2xATR stop, 3R (best cell found) | Raw | 1127 | -0.0111 / 0.98 | +0.0338 / 1.05 | -0.0804 / 0.88 | fail (OOS) |
| 1H | 4H+1H bias, 4H/D corners, 2xATR stop, 5R | Standard | 6998 | -0.0959 / 0.86 | -0.0820 / 0.88 | -0.1172 / 0.83 | fail |
| 1H | 4H+1H bias, 4H/D corners, 2xATR stop, 5R | Raw | 6998 | -0.1318 / 0.82 | -0.1184 / 0.84 | -0.1522 / 0.79 | fail |

The gate chart in the README widens this to a 96-cell 4H grid: target 1.5, 2, 2.5 or 3R; stop 1, 1.5 or
2 ATR; corner tolerance 0.75 or 1.5 ATR; d4 or 2-of-3 bias; Standard or Raw account; all at 1.5x cost.
None of the 96 is positive in both halves. Putting the one-bar look-ahead back into the old headline
config moves it from IS -0.0016 / OOS -0.1372 to IS +0.0935 / OOS -0.0067, right up to the edge of
the pass zone.

The best cell is the textbook overfit shape: positive in-sample, negative out-of-sample. It is a peak
in a compact grid where no cell clears the gate, not a plateau. Rebuild this table with
`python scripts/reproduce_results.py` ([reports/results_table.md](../reports/results_table.md)).

## How I got here

**1. Three rule-based strategies lost money once they were measured honestly.** V1 (structure plus ATR),
V2 (corner areas of interest) and V3 (4H corners with a 1H confirmation) were rebuilt on broker-time
candles, with higher-timeframe bias visible only after its bar had closed, and net of cost. All three are
net negative ([reports/strategy_honest_comparison.md](../reports/strategy_honest_comparison.md)):

All 18 instruments, net of 1x cost:

| Strategy | Trades | PF | avg R | total R | OOS PF | OOS total R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| V1 structure + ATR (2 of 3 bias) | 42,450 | 0.74 | -0.1908 | -8,100 | 0.75 | -3,048 |
| V2 corner AOI (2 of 3 bias) | 3,818 | 0.77 | -0.1576 | -602 | 0.76 | -300 |
| V3 4H corner (as written) | 179 | 0.85 | -0.1009 | -18 | 1.11 | +5 |

V3's small out-of-sample gain sits on an in-sample loss, a few dozen trades, and a 1H confirmation that
looks past its own entry: it confirmed on a 1H close that happens after the trade was opened. The
15 June version of this report predates the pivot fix (fewer trades, same verdict); the table above is
the rerun on the corrected engine.

**2. A distilled edge looked real.** A confluence lab tagged every 4H bar with which conditions were
present and ranked them. Only one combination seemed to carry the result: daily and 4H trend agree,
price pulls back into a *fresh* swing corner (one of the last two confirmed daily or weekly pivots) and
closes back through it. Trading that with a 1 ATR stop and a 5R target, I reported **PF 1.31 at roughly
1.5x cost, out-of-sample PF 1.22**. Those numbers were wrong, as step 3 shows.

**3. I found the leak.** A swing pivot only exists once the candles to its right (two on the daily, one on
the weekly) have closed. The code stamped its confirmation at the **open** of the rightmost candle instead
of its **close**. Daily and weekly corners
therefore became tradeable up to a full daily bar before they could have been known. A second, subtler
leak let a historical pivot be revised when later bars arrived.

**4. I proved the fix with a parity gate.** For every historical signal bar plus a recent window, the gate
truncates the raw H1 feed at that bar's close (exactly what a live bot would hold), rebuilds everything
from scratch through the live code path, and compares the signal with the full-history backtest. Any
difference is look-ahead. After the first fix the gate still flagged 33 bars on two pairs, which is how
the second leak was found. Final result on all 12 pairs: **3,745 checks, 0 mismatches**, and the
sequential trade lists match ([reports/replay_parity.txt](../reports/replay_parity.txt)).

**5. The edge did not survive.** The same configuration on causal data: 1,372 trades, PF 0.96 at 1x cost,
in-sample PF 1.03, out-of-sample PF 0.87 ([reports/edge_gauntlet.md](../reports/edge_gauntlet.md)). A compact
grid over target, stop, tolerance and bias, a 1H port with cost levers, partial exits, and 30m and 15m
probes produced nothing that is net positive at 1.5x cost in both halves
([reports/edge_corrected_findings.md](../reports/edge_corrected_findings.md)).

`tests/test_lookahead_shift.py` keeps the lesson honest. Re-introducing just the one-bar pivot
misalignment moves the same strategy from **-0.031R per trade, PF 0.96** to **+0.081R, PF 1.10**, and
out-of-sample PF from 0.87 to 1.02. One bar of misalignment is enough to make a losing system look
deployable.

## Every canonical run

```bash
python scripts/verify_broker_time.py
python scripts/replay_parity.py all 5
python scripts/run_edge_strategy.py --gauntlet --bias-mode d4 --target-rr 5.0 --instruments AUDUSD,EURUSD,EURGBP,NZDJPY,EURJPY,USDJPY,GBPUSD,USDCAD,AUDJPY,GBPJPY,GBPCHF,NZDUSD
python scripts/run_strategy_honest.py
```

## What is in the repo

```
src/fxresearch/
  data/         DukascopyHandler (loader), DukascopyDownloader, instrument metadata
  clock/        BrokerClock: GMT+2/+3 candles, 17:00 New York close, US DST; its 17 checks
  costs/        CostModel: measured spreads, Standard and Raw accounts, cost in R
  structure/    PivotHandler, StructureHandler and StructureReader, AOIs, fresh corners, candle patterns
  engine/       FrameBuilder, trade simulator, ATR, performance metrics
  strategies/   V1, V2, V3 (and its causal rebuild), the edge
  analysis/     gauntlet, honest V1-V3 comparison, confluence lab, monthly, scale-out, timeframe,
                intraday, risk Monte Carlo, the results table
  live/         LiveSignalHandler, ParityGate, cTrader auth and bot
scripts/        thin command-line entry points
tests/          broker clock, cost model, parity gate, look-ahead shift, regression on the corrected numbers
reports/        only the reports cited here, see reports/README.md
docs/           methodology.md (costs, look-ahead controls, IS/OOS, the gate), ctrader_setup.md
```

[methodology.md](methodology.md) explains every control. The cTrader bot
([ctrader_setup.md](ctrader_setup.md)) runs the parity-tested signal on a demo account in
dry-run mode. It exists to prove the execution plumbing, not to trade: there is no edge to deploy.

## Limitations

- Bid-only prices with a modeled spread. No real fills, slippage model or swap and financing costs, and
  the edge holds trades for up to ten days, so swaps would matter.
- One broker's clock and cost structure. The 1.5x spread multiplier is an estimate.
- Many configurations were tried over the same history. The out-of-sample half guards against the worst of
  it, but the reported best cell is still the maximum of a search, which biases it upwards.
- M15 data was only complete for two pairs, so the 30m and 15m results are a probe, not a universe test.

## What I would do next

1. **Treat the data after 2026-06-12 as a true forward test.** Freeze one pre-registered configuration and
   evaluate it once on data no version of this code has seen.
2. **Correct for the search.** Count the configurations tried and report a deflated Sharpe ratio or a
   White's reality check p-value instead of a raw best cell.
3. **Measure costs instead of modelling them.** Run the dry-run bot against a demo account long enough to
   record real spreads at signal times and compare them with the 1.5x assumption.
4. **Change the signal family, not the parameters.** The structure-pullback idea is exhausted on this data.
   Cross-sectional carry or momentum across the 12 pairs holds positions longer, which amortises the cost
   that killed every intraday variant here.
