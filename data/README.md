# Data

Prices are **not** in this repository. Dukascopy's terms do not allow redistributing their feed, and the
full set is about 135 MB. Rebuild it locally with the downloader, which wraps the
[dukascopy-node](https://github.com/Leo4815162342/dukascopy-node) CLI (needs Node.js for `npx`).

## What the results use

Every backtest reads only the **bid H1** files, `data/dukascopy/{INSTRUMENT}_h1.csv`. Higher timeframes
(4H, daily, weekly) are rebuilt from H1 on the broker clock, never taken from a vendor daily file.

The reported research window is **2015-01-01 to 2026-06-12** (last H1 bar 2026-06-12 20:00 UTC).
Pin the end date when downloading, or newer bars will change every number:

```bash
python scripts/download_dukascopy.py --from 2015-01-01 --to 2026-06-14 --timeframes h1 --instruments AUDUSD,EURUSD,EURGBP,NZDJPY,EURJPY,USDJPY,GBPUSD,USDCAD,AUDJPY,GBPJPY,GBPCHF,NZDUSD
```

That is the 12-pair universe behind the main results table, the edge gauntlet and the parity gate.
`run_strategy_honest.py` also uses the six expensive instruments (AUDCHF, NZDCAD, XAUUSD, XAGUSD, XPTUSD,
COPPER); drop `--instruments` to fetch all 18.

## Optional files

| File | Used by | How to get it |
| --- | --- | --- |
| `{INSTRUMENT}_h1_ask.csv` | calibrating `costs/cost_model.py` spreads (mean ask minus bid, 2023 to 2026) | `--price ask --timeframes h1` |
| `{INSTRUMENT}_m15.csv` | 15m and 30m probes in `run_edge_intraday.py` | `--timeframes m15` |
| `{INSTRUMENT}_d1.csv` | nothing in the pipeline; kept for eyeballing | `--timeframes d1` |

M15 coverage in the original research was incomplete (only EURJPY and NZDJPY end to end), which is why
the 15m and 30m rows in `reports/edge_corrected_findings.md` are marked data-limited.

## Format

One CSV per instrument and timeframe, header `timestamp,open,high,low,close`, timestamp in UTC epoch
milliseconds. `fxresearch.data.dukascopy.DukascopyHandler` loads it into a sorted, de-duplicated,
UTC-indexed OHLC frame.

## Reproducibility caveat

Dukascopy occasionally revises history. A fresh download over the same dates should match, but if a
regression test fails by a trade or two, compare row counts per file before suspecting the code. The
original files had 71,336 to 71,358 H1 rows per KEEP12 pair.
