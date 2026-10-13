# cTrader demo harness: setup

`scripts/ctrader_bot.py` connects to a **cTrader demo** account through Spotware's Open API and runs the
parity-tested 4H signal (`live/signal.py`). Treat it as an execution and plumbing exercise:
**no configuration in this repo cleared the 1.5x-cost gate, so there is nothing here worth trading.** It
defaults to `dry_run`, which logs signals and the orders it would send, and places nothing.

What has and has not been verified:

- The signal path is proven identical to the backtest by `scripts/replay_parity.py` (0 mismatches over 3,745 bars).
- The cTrader I/O layer (auth, history, live bars, order placement) has **not** been exercised against
  the SDK in this repository; it is untested code. Position sizing is a fixed minimal volume placeholder.

## 1. Demo account and app

1. Open a cTrader **demo** account with a broker that offers cTrader.
2. At <https://openapi.ctrader.com/> create an application and set its Redirect URI to exactly
   `http://localhost:5000/`. Note the client id and client secret.

## 2. Credentials, never in git

Either export environment variables (preferred):

```bash
export CTRADER_CLIENT_ID=...
export CTRADER_CLIENT_SECRET=...
```

or copy the template to the git-ignored local file and fill it in:

```bash
cp config/ctrader_config.example.json config/ctrader_config.json
```

Environment variables override the file. `config/ctrader_config.json` is listed in `.gitignore`.

## 3. OAuth token

```bash
python scripts/ctrader_auth.py
```

This opens the browser, catches the redirect on `localhost:5000`, exchanges the code and writes only the
access and refresh tokens into `config/ctrader_config.json`. You can export `CTRADER_ACCESS_TOKEN`
instead.

## 4. Account id and dry run

```bash
pip install -r requirements-live.txt
python scripts/ctrader_bot.py --list-accounts
python scripts/ctrader_bot.py
```

Put the demo `ctidTraderAccountId` into `CTRADER_ACCOUNT_ID` (or `account_id` in the local file). With
`dry_run: true` the bot loads 540 days of H1 per symbol, subscribes to live H1 bars, acts only when a
broker-clock 4H bar has closed, and logs a heartbeat line per symbol every 15 minutes.

Hosts: demo `demo.ctraderapi.com:5035`, live `live.ctraderapi.com:5035`.
