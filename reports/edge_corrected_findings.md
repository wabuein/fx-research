# Corrected Edge Findings - causal retest

Date: 2026-06-16

## Verdict

The old reported 4H result, PF 1.31 / OOS PF 1.22, was look-ahead inflated and
must not be used. After fixing pivot confirmation and causal alternation, the
live/backtest parity gate passes, but no tested configuration is net-positive at
1.5x cost in both IS and OOS.

No performance whitelist is justified.

## Step 0: parity gate

Fixes applied:

- `base.pivots()` now timestamps `confirm` at the close/availability time of the
  rightmost lookahead candle, not that candle's open.
- `base.alternating_pivots()` is prefix-stable: once an alternating pivot is
  emitted, later same-type pivots do not revise it.
- `structure_timeline()` consumes pivots by candle close time, so states and
  AOIs share the same causal confirmation model.
- `run_edge_strategy._precompute_corners()` now uses pivot `confirm` directly
  because the base pivot confirm is already a close/availability timestamp.

Replay result:

```text
python3 scripts/replay_parity.py all 5
TOTAL checked=3745 mismatch=0 sequential_parity=ALL OK
VERDICT: PARITY PROVEN - live == backtest, no look-ahead
```

## Data coverage

KEEP12 H1/D1 data covers 2015-01-01 through 2026-06-12.

M15 is not complete for KEEP12. Complete through 2026-06-15 only:

- `EURJPY`
- `NZDJPY`

Partial M15:

- `AUDUSD` through 2020-01-03 after the interrupted refresh attempt
- `EURUSD` through 2017-05-19
- `EURGBP` through 2023-12-14

Missing M15:

- `USDJPY`, `GBPUSD`, `USDCAD`, `AUDJPY`, `GBPJPY`, `GBPCHF`, `NZDUSD`

30m was added as a broker-EET resample from M15, so 30m results are only valid
for instruments with M15 coverage. The 15m/30m rows below are therefore a
data-limited probe, not a KEEP12 universe result.

## Head-to-head at the real gate

Best-tested means the strongest cell found in the compact retest or built-in
scan, not an approved production config.

| TF | Data | Best-tested config | Account | 1.5x full | 1.5x IS | 1.5x OOS | Gate |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 4H | KEEP12 | rr3 stop2 tol0.75 d4 | Standard | avg +0.0054 PF 1.01 | avg +0.0504 PF 1.08 | avg -0.0641 PF 0.91 | Fail OOS |
| 4H | KEEP12 | rr3 stop2 tol0.75 d4 | Raw | avg -0.0111 PF 0.98 | avg +0.0338 PF 1.05 | avg -0.0804 PF 0.88 | Fail OOS |
| 1H | KEEP12 | rr5 stop2 corners | Standard | avg -0.0959 PF 0.86 | avg -0.0820 PF 0.88 | avg -0.1172 PF 0.83 | Fail |
| 1H | KEEP12 | rr5 stop2 corners | Raw | avg -0.1318 PF 0.82 | avg -0.1184 PF 0.84 | avg -0.1522 PF 0.79 | Fail |
| 30m | EURJPY,NZDJPY only | rr5 stop2 corners | Standard | avg -0.0626 PF 0.92 | avg -0.0316 PF 0.96 | avg -0.1092 PF 0.86 | Fail, data-limited |
| 30m | EURJPY,NZDJPY only | rr5 stop2 corners | Raw | avg -0.1204 PF 0.85 | avg -0.0941 PF 0.88 | avg -0.1602 PF 0.80 | Fail, data-limited |
| 15m | EURJPY,NZDJPY only | rr5 stop2 corners | Standard | avg -0.1439 PF 0.82 | avg -0.1473 PF 0.81 | avg -0.1386 PF 0.83 | Fail, data-limited |
| 15m | EURJPY,NZDJPY only | rr5 stop2 corners | Raw | avg -0.2271 PF 0.73 | avg -0.2367 PF 0.72 | avg -0.2119 PF 0.75 | Fail, data-limited |

## 4H details

Baseline 2R after causal fix:

- Full: 1486 trades, avg -0.1138R, PF 0.84
- IS: avg -0.0788R, PF 0.89
- OOS: avg -0.1685R, PF 0.77

Old wide-target 5R after causal fix:

- Full: 1372 trades, avg -0.0307R, PF 0.96
- IS: avg +0.0216R, PF 1.03
- OOS: avg -0.1127R, PF 0.87

Compact 4H grid tested rr 1.5-3.0, stop 1.0-2.0 ATR, AOI tolerance 0.75/1.5,
and d4/bias2 under Standard and Raw 1.5x. Clear cells: 0. Best OOS cell still
lost OOS.

## 1H details

The built-in 1H scan found no rescue:

- Baseline corners 5R/1ATR/60 bars: Standard 1.5x full avg -0.1895R, OOS avg
  -0.2131R.
- Stop 2ATR improved cost drag but still failed: Standard 1.5x full avg
  -0.0959R, OOS avg -0.1172R.
- AOI source, volatility percentile, min-risk, EMA trend, and session filters
  stayed negative.

## 30m / 15m subset

These are not universe-valid because M15 coverage is incomplete. On the two
complete M15 pairs (`EURJPY,NZDJPY`):

- 30m stop 2ATR had IS slightly positive at 1x, but OOS was negative and 1.5x
  failed.
- 15m remained negative even with stop 2ATR and min-risk filters.

## Partial exits

4H partial-TP/BE variants on KEEP12 did not rescue OOS at 1.5x:

| Config | Account | Full avg/PF | IS avg/PF | OOS avg/PF |
| --- | --- | ---: | ---: | ---: |
| 50%@1R + 50%@3R, BE | Standard | -0.0265 / 0.95 | +0.0233 / 1.05 | -0.1038 / 0.81 |
| 50%@1R + 50%@3R, no BE | Standard | -0.0258 / 0.95 | +0.0210 / 1.04 | -0.0980 / 0.83 |
| 50%@1R + 50%@3R, BE | Raw | -0.0430 / 0.92 | +0.0068 / 1.01 | -0.1201 / 0.78 |

## Conclusion

After the causal fix and parity proof, the apparent edge is not robust. The
strongest 4H cell is an IS-positive/OOS-negative shape, not a plateau. 1H is
negative across the scan. 30m/15m cannot be honestly promoted because the M15
universe is incomplete, and even the complete-pair subset fails.

Do not repoint `live_signal.py` / `ctrader_bot.py` to any winning config,
because no real winning config cleared the gate.
