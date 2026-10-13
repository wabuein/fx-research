# Methodology

How the numbers in this repo are produced, and every control that stands between a backtest and a
fooled researcher. Code references are to `src/fxresearch/`.

## 1. Data

**Source.** Dukascopy bid OHLC, H1, 2015-01-01 to 2026-06-12, 18 instruments (14 FX pairs, gold,
silver, platinum, copper). The research started on Yahoo Finance and moved off it for two reasons:
Yahoo caps hourly history at 730 days, and it serves futures *proxies* (GC=F, SI=F, PL=F, HG=F)
instead of the spot metals a CFD broker quotes. See `data/README.md` for the download.

**One source of truth.** Only H1 is read. 4H, daily and weekly candles are aggregated from it
(`clock/broker_clock.py`), so every timeframe shares one clock and one feed.

## 2. The broker clock

The original backtests cut candles on UTC: 4H at 00/04/08 UTC, daily at UTC midnight. A
Pepperstone (MT4/MT5/cTrader) chart is cut on server time, which is EET-like: GMT+2 in winter,
GMT+3 in summer, with the daily candle closing at **17:00 New York**. Every 4H trigger candle and
every daily or weekly pivot was therefore different from what the chart showed.

Server midnight is defined as 17:00 New York, and the DST switch follows the **US** calendar:

```
broker wall clock = New York wall clock + 7 hours
```

In UTC that boundary is 21:00 when New York is on summer time and 22:00 in winter. No fixed UTC
offset can express both, which is why a "+2" or "+3" patch is still wrong. `BrokerClock.to_broker_time`
converts UTC to `America/New_York`, drops the zone and adds seven hours, so pandas applies the DST rule.
The result is a naive index that reads exactly like the broker platform.

- 4H and daily buckets are anchored to broker midnight (`origin="start_day"`), so 4H opens land on
  0/4/8/12/16/20 and the daily opens at 00:00.
- Weekly is a `W-FRI` aggregation of the broker daily: a candle spans Monday to Friday and is
  labelled on its Friday.
- The autumn fall-back hour repeats one broker label a year (a Sunday, with the market shut); the
  first occurrence is kept.
- If a broker turned out to follow EU DST instead, only `BROKER_DST_REFERENCE` would change.

`tests/test_broker_clock.py` (and `scripts/verify_broker_time.py`) assert all of this: synthetic bars
for both DST regimes, plus 17 checks on the real EURUSD history. One of them proves a broker daily close
differs from the old UTC daily close on the same date.

## 3. Costs (`costs/cost_model.py`)

Results are in **R**, multiples of the risk taken. A round-trip cost is a fixed price distance, so in
R it is `cost_pips / risk_pips`. That is the whole reason tight stops (and lower timeframes) die: the
same spread is a bigger slice of a smaller stop.

- **Spread.** `ROUND_TRIP_COST_PIPS` is the measured mean Dukascopy ask minus bid, 2023 to 2026 H1,
  in each instrument's pip. On a bid-based backtest the round-trip spread cost is about one spread (a
  long pays it on entry at the ask, a short on exit at the ask).
- **Standard account** (spread only, no commission): `cost = spread x mult / risk_pips`.
- **Raw account** (near-raw spread plus a fixed $7 per 100k round trip):
  `cost = (spread x 1.1 x mult + commission_pips) / risk_pips`. `mult` stresses only the spread; the
  commission is a fixed pip cost that does not shrink with the stop.
- **Treat Dukascopy as a floor.** A retail Standard account runs wider, so the gate uses
  **1.5x**. `mult` 1.0 means Dukascopy raw, and anything has to survive 1.5x to be tradeable.

## 4. Look-ahead controls

Each item below was a real or near-real leak at some point in this research.

1. **Pivot confirmation time.** A swing pivot with a 2-bar right window is only known once the
   rightmost window candle has *closed*. `PivotHandler` stamps `confirm` with that candle's close
   (`bar_close_times`: the next bar's open, the last bar's open plus the median spacing). The bug that
   inflated the old edge stamped it at that candle's **open**, so daily and weekly corners became
   usable up to a full daily bar early. `CONFIRM_AT_OPEN` keeps the leaky variant available only so a test can prove
   the difference (section 7).
2. **Prefix-stable alternation.** The original zigzag rewrote the last same-type pivot when a more
   extreme one appeared later. A historical pivot could therefore change when future bars arrived.
   `PivotHandler.alternate` only emits; it never revises.
3. **Higher-timeframe state at bar close.** A structure timeline is indexed by each bar's *open*,
   but its state is computed at that bar's *close*. Looking it up by open time hands a 4H signal the
   still-forming daily or weekly bar. `StructureReader.closed_states` re-keys every timeline to bar
   close and as-of joins backwards. The V1 to V3 comparison does the same by re-indexing every
   timeline to its close times before any lookup.
4. **Next-bar entry.** Signals use only bars up to and including the just-closed bar `i`; entry is at
   the open of `i + 1` (or later).
5. **Conservative fills.** If one candle touches both stop and target, it is a stop
   (`engine/simulator.py`).
6. **V3's confirmation bug.** V3 "as written" confirms on 1H closes in `(open i, open i+1]` but enters
   at the open of `i + 1`. A 1H candle can never close beyond its own parent 4H extreme, so the only
   confirmations it ever found were the leaked first 1H bar of the *next* 4H candle. That bar closes
   after the entry. `BrokerCornerStrategy` fixes it: confirm during bar `i + 1`, enter at `i + 2`.

## 5. In-sample and out-of-sample

- **Split:** in-sample is every trade with a signal before 2022 (2015 to 2021); out-of-sample is 2022
  onward (`engine/metrics.py`, `SPLIT_YEAR`).
- **The gate:** a configuration counts only if it is net positive in **both** halves at **1.5x** cost.
  A config that is positive in-sample and negative out-of-sample is a fit, not an edge.
- **Universe selection without peeking:** the 12-pair KEEP12 universe drops the four metals and
  commodities plus NZDCAD and AUDCHF on *spread cost alone* (0.1 to 0.39 R per trade), a structural
  reason that does not look at returns. The gauntlet's whitelist is chosen on in-sample results only
  and then judged out-of-sample. It still fails.
- **Plateau checks:** the gauntlet sweeps target, stop, AOI tolerance and bias mode around the chosen
  point. An edge should sit on a plateau, not a spike.

## 6. The strategies

| Version | Code | Idea |
| --- | --- | --- |
| V1 | `strategies/v1_structure_atr.py` | W/D/4H structure bias (2 of 3), a Tier-1 candle trigger at a reaction level or a 1H EMA, stop beyond 1H/4H protected structure plus 0.25 ATR, target 2x 1H ATR. `enhanced` adds AOI and confirmation rules. |
| V2 | `strategies/v2_corner_aoi.py` | Same bias and trigger, entry only at a daily or weekly *corner* (a confirmed swing) or a cluster of them, target the nearest opposing corner at 1R to 2.5R. |
| V3 | `strategies/v3_4h_corner.py` | 4H signals at clean latest corners, 1H confirmation, cluster targets near 1.8R. `BrokerCornerStrategy` is the causal rebuild. |
| Edge | `strategies/edge.py` | The distilled version: daily and 4H structure agree, price wicks into a *fresh* corner (one of the last two confirmed daily or weekly pivots) and closes back through it, fixed `k x ATR` stop, `n R` target, one position per instrument. |

The edge came from the **confluence lab** (`analysis/confluence_lab.py`). It tags every 4H bar, long
and short, with which confluences are present, then scores two lenses:

- **A**: a fixed 1x ATR stop with 0.5R to 2R targets.
- **B**: the structure stop and opposing-AOI target.

`analysis/confluence_analyzer.py` ranks single confluences and 2 to 3 stacks by win rate and
net expectancy, in-sample and out-of-sample. The lab's ranking was produced **before** the pivot fix.
It suggested higher-timeframe bias plus a fresh corner was the only confluence that mattered. That
hypothesis is what the corrected gauntlet then failed to confirm.

## 7. The parity gate (`live/parity.py`)

The live bot and the backtest call the same `EdgeStrategy.signal_at` on frames from the same
`FrameBuilder`. Sharing code is not proof, so the gate tests it from the outside:

1. Build the full-history frames and record the signal at every bar (the "truth").
2. For a recent window **plus every historical signal bar**, truncate the raw H1 feed at that 4H bar's
   close, exactly what a live bot would hold at that instant. Then rebuild every frame, structure
   timeline and pivot from scratch through the live path and evaluate the last bar.
3. Compare direction, risk, corner timeframe and corner price. Any difference means the full-history
   backtest knew something the live bot could not have: look-ahead.
4. Rebuild the sequential trade list from the shared signal and bracket functions and check it equals
   `EdgeStrategy.simulate` trade for trade.

Result on KEEP12 (`reports/replay_parity.txt`): **3,745 bars checked, 0 mismatches, sequential
parity on all 12 pairs.**

The gate earned its keep before it passed. After the first fix (pivot confirm moved from open to
close), it still flagged 10 of 251 EURUSD bars and 23 of 176 AUDJPY bars. Live and backtest disagreed
because the old alternation step could still revise a historical pivot when later bars arrived.
Making alternation prefix-stable (section 4, item 2) took the count to zero.

Two tests pin this down:

- `tests/test_replay_parity.py` runs the gate on AUDJPY and also proves the gate *catches* the leaky
  pivot variant.
- `tests/test_lookahead_shift.py` stamps pivots one bar early and shows the backtest gets
  suspiciously better: net R per trade goes from **-0.031R (PF 0.96)** to about **+0.081R (PF 1.10)**,
  and OOS PF goes from 0.87 to about 1.02. A one-bar misalignment alone turns a losing system into a
  plausible one.

## 8. Faster timeframes and partial exits

`analysis/intraday.py` ports the fresh-corner idea to 1H, 30m, 15m and 5m signals. The bias and
corner timeframes scale down with the signal, and it adds cost levers: a minimum stop in pips, an ATR
percentile floor, wider ATR stops, intraday AOIs (prior day and week high and low, round numbers), an EMA trend filter and session
windows. Smaller ATR means a tighter stop, so cost per R grows and every variant fails the gate.
`analysis/scaleout.py` tests partial take-profit plus break-even. It lifts the win rate and smooths
equity, but it does not create expectancy.

## 9. Reproducing

```bash
python scripts/verify_broker_time.py                 # 17 clock checks
python scripts/replay_parity.py all 5                # the parity gate on KEEP12, about 13 minutes
python scripts/run_edge_strategy.py --gauntlet --bias-mode d4 --target-rr 5.0 --instruments AUDUSD,EURUSD,EURGBP,NZDJPY,EURJPY,USDJPY,GBPUSD,USDCAD,AUDJPY,GBPJPY,GBPCHF,NZDUSD
python scripts/run_strategy_honest.py                # V1/V2/V3 head to head, about an hour
python scripts/reproduce_results.py                  # the README table
python scripts/make_figures.py                       # the two README images, including the 96-cell gate grid
pytest
```

## 10. Map from the original scripts

The refactor moved code into a package without changing a computed number; the four canonical runs
were diffed before and after (only em dashes and printed file paths differ).

| Original script | Now |
| --- | --- |
| `dukascopy_data.py`, `download_dukascopy.py` | `data/dukascopy.py`, `data/downloader.py`, `data/instruments.py` |
| `broker_time.py`, `verify_broker_time.py` | `clock/broker_clock.py`, `clock/verification.py` |
| `cost_model.py` | `costs/cost_model.py` |
| `backtest_structure_atr_strategy.py` (base engine + V1) | `structure/*`, `engine/indicators.py`, `engine/simulator.py`, `strategies/v1_structure_atr.py` |
| `backtest_corner_aoi_strategy.py` | `strategies/v2_corner_aoi.py` |
| `backtest_v3_4h_corner_strategy.py`, `run_v3_broker.py` | `strategies/v3_4h_corner.py`, `engine/frames.py` |
| `run_edge_strategy.py` | `strategies/edge.py`, `analysis/gauntlet.py` |
| `run_strategy_honest.py` | `analysis/honest_comparison.py` |
| `confluence_lab.py`, `confluence_analyze.py` | `analysis/confluence_lab.py`, `analysis/confluence_analyzer.py` |
| `run_edge_monthly.py`, `run_edge_scaleout.py`, `run_edge_tf.py`, `run_edge_risk.py`, `run_edge_intraday.py` | `analysis/monthly.py`, `scaleout.py`, `timeframe.py`, `risk.py`, `intraday.py` |
| `live_signal.py`, `replay_parity.py` | `live/signal.py`, `live/parity.py` |
| `ctrader_auth.py`, `ctrader_bot.py` | `live/config.py`, `live/ctrader_auth.py`, `live/ctrader_bot.py` |

The original comparison harness monkeypatched two functions into the base module. A faster
state lookup and a 260-bar EMA window are now constructor arguments (`StructureReader(fast_lookup=True)`,
`StructureAtrStrategy(ema_tail=260)`), so the same behaviour is explicit.
