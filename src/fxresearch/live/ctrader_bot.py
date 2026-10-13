from __future__ import annotations

import datetime as dt
import sys
from typing import Any

import numpy as np
import pandas as pd

from fxresearch.live.config import CTraderConfig
from fxresearch.live.signal import LiveSignal, LiveSignalHandler

# enough h1 history for daily and weekly structure plus the warmup
H1_HISTORY_DAYS = 540
DEFAULT_HEARTBEAT_SECONDS = 900
# 0.01 lot in ctrader volume units, a placeholder until sizing is validated on demo
DEFAULT_FIXED_VOLUME = 100000


def log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def load_sdk() -> dict[str, Any]:
    # imported lazily so --help and the research code work without the sdk installed
    try:
        from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAAccountAuthReq,
            ProtoOAApplicationAuthReq,
            ProtoOAGetAccountListByAccessTokenReq,
            ProtoOAGetTrendbarsReq,
            ProtoOANewOrderReq,
            ProtoOASubscribeLiveTrendbarReq,
            ProtoOASymbolsListReq,
        )
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
            ProtoOAOrderType,
            ProtoOATradeSide,
            ProtoOATrendbarPeriod,
        )
        from twisted.internet import reactor
    except ImportError as error:
        sys.exit(f"cTrader SDK not installed: {error}\n  pip install -r requirements-live.txt")
    return locals()


def trendbars_to_df(bars: list[Any]) -> pd.DataFrame:
    # prices are deltas from low in 1e-5 units, timestamps are minutes since the epoch
    rows = []
    for bar in bars:
        low = bar.low / 1e5
        open_ = (bar.low + bar.deltaOpen) / 1e5
        high = (bar.low + bar.deltaHigh) / 1e5
        close = (bar.low + bar.deltaClose) / 1e5
        ts = pd.Timestamp(bar.utcTimestampInMinutes * 60, unit="s", tz="UTC")
        rows.append((ts, open_, high, low, close, float(getattr(bar, "volume", 0))))

    df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    return df.set_index("ts").sort_index()


class CTraderHandler:

    def __init__(self, config: CTraderConfig, sdk: dict[str, Any], signals: LiveSignalHandler,
                 list_only: bool = False) -> None:
        self.dry_run = bool(config.get("dry_run", True))
        self.account_id = int(config.get("account_id", 0) or 0)
        self.symbols = list(config.get("symbols", []))
        self.list_only = list_only

        self.config = config
        self.sdk = sdk
        self.signals = signals
        self.clock = signals.context.clock
        self.client = None

        self.symbol_ids: dict[str, int] = {}
        self.symbol_meta: dict[str, dict] = {}
        self.h1: dict[str, pd.DataFrame] = {}
        self.last_4h_open: dict[str, pd.Timestamp] = {}

    def run(self) -> None:
        sdk = self.sdk
        host = self.config.get("host", sdk["EndPoints"].PROTOBUF_DEMO_HOST)
        port = int(self.config.get("port", sdk["EndPoints"].PROTOBUF_PORT))

        self.client = sdk["Client"](host, port, sdk["TcpProtocol"])
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(lambda client, reason: log(f"disconnected: {reason}"))
        self.client.setMessageReceivedCallback(self._on_message)
        self.client.startService()
        sdk["reactor"].run()

    def _send(self, request: Any, callback: Any) -> Any:
        deferred = self.client.send(request)
        deferred.addErrback(lambda failure: log(f"ERR {type(request).__name__}: {failure.getErrorMessage()}"))
        if callback:
            deferred.addCallback(callback)
        return deferred

    def _on_connected(self, _client: Any) -> None:
        log("connected; authenticating application")
        request = self.sdk["ProtoOAApplicationAuthReq"](clientId=self.config.require("client_id"),
                                                         clientSecret=self.config.require("client_secret"))
        self._send(request, self._on_app_auth)

    def _on_app_auth(self, _response: Any) -> None:
        access_token = self.config.require("access_token")
        if self.list_only:
            log("listing accounts for this access token")
            self._send(self.sdk["ProtoOAGetAccountListByAccessTokenReq"](accessToken=access_token),
                       self._on_account_list)
            return

        log("authenticating the configured account")
        self._send(self.sdk["ProtoOAAccountAuthReq"](ctidTraderAccountId=self.account_id, accessToken=access_token),
                   self._on_account_auth)

    def _on_account_list(self, response: Any) -> None:
        message = self.sdk["Protobuf"].extract(response)
        print("\n  ctidTraderAccountId   broker            live?")
        for account in message.ctidTraderAccount:
            print(f"  {account.ctidTraderAccountId:<20} {getattr(account, 'brokerName', '?'):<16} "
                  f"{'LIVE' if account.isLive else 'demo'}")
        print("\nPut the demo id into CTRADER_ACCOUNT_ID or the local config account_id\n")
        self.sdk["reactor"].stop()

    def _on_account_auth(self, _response: Any) -> None:
        log("account authed; loading symbols")
        self._send(self.sdk["ProtoOASymbolsListReq"](ctidTraderAccountId=self.account_id), self._on_symbols)

    def _on_symbols(self, response: Any) -> None:
        message = self.sdk["Protobuf"].extract(response)
        wanted = set(self.symbols)
        for symbol in message.symbol:
            if symbol.symbolName not in wanted: continue
            self.symbol_ids[symbol.symbolName] = symbol.symbolId
            self.symbol_meta[symbol.symbolName] = {"digits": symbol.digits,
                                                   "pipPosition": getattr(symbol, "pipPosition", 4)}

        missing = wanted - set(self.symbol_ids)
        if missing:
            log(f"WARN symbols not found on this account: {sorted(missing)}")
        log(f"tracking {len(self.symbol_ids)} symbols; fetching {H1_HISTORY_DAYS}d H1 history")
        for name in self.symbol_ids:
            self._fetch_history(name)

    def _fetch_history(self, name: str) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        start = now - dt.timedelta(days=H1_HISTORY_DAYS)
        request = self.sdk["ProtoOAGetTrendbarsReq"](
            ctidTraderAccountId=self.account_id, symbolId=self.symbol_ids[name],
            period=self.sdk["ProtoOATrendbarPeriod"].H1,
            fromTimestamp=int(start.timestamp() * 1000), toTimestamp=int(now.timestamp() * 1000))
        self._send(request, lambda response, n=name: self._on_history(n, response))

    def _on_history(self, name: str, response: Any) -> None:
        message = self.sdk["Protobuf"].extract(response)
        self.h1[name] = trendbars_to_df(message.trendbar)
        log(f"  {name}: {len(self.h1[name])} H1 bars loaded")

        # live h1 updates tell us when bars complete
        self._send(self.sdk["ProtoOASubscribeLiveTrendbarReq"](
            ctidTraderAccountId=self.account_id, symbolId=self.symbol_ids[name],
            period=self.sdk["ProtoOATrendbarPeriod"].H1), None)
        self._evaluate(name, initial=True)
        if name == list(self.symbol_ids)[-1]:
            self._schedule_heartbeat()

    def _on_message(self, _client: Any, message: Any) -> None:
        try:
            message = self.sdk["Protobuf"].extract(message)
        except Exception:
            return

        if type(message).__name__ != "ProtoOASpotEvent" or not getattr(message, "trendbar", None): return
        name = self._name_of(message.symbolId)
        if not name: return

        for bar in message.trendbar:
            self._ingest_bar(name, bar)
        self._evaluate(name)

    def _name_of(self, symbol_id: int) -> str | None:
        return next((name for name, sid in self.symbol_ids.items() if sid == symbol_id), None)

    def _ingest_bar(self, name: str, bar: Any) -> None:
        df = trendbars_to_df([bar])
        if df.empty: return

        merged = pd.concat([self.h1[name], df])
        self.h1[name] = merged[~merged.index.duplicated(keep="last")].sort_index()

    def _evaluate(self, name: str, initial: bool = False) -> None:
        # act only once a 4h bar has fully closed: the newest h1 entering a new bucket closes the previous one
        if name not in self.h1 or self.h1[name].empty: return

        broker_index = self.clock.to_broker_time(self.h1[name]).index
        if len(broker_index) == 0: return

        current_bucket = broker_index[-1].floor("4h")
        previous = self.last_4h_open.get(name)
        if not initial and previous is not None and current_bucket == previous: return

        self.last_4h_open[name] = current_bucket
        self._signal_for_close(name, broker_index, current_bucket)

    def _signal_for_close(self, name: str, broker_index: pd.DatetimeIndex, current_bucket: pd.Timestamp) -> None:
        # h1 strictly before the forming bucket, so the last 4h bar is the closed one, as the parity gate checks
        closed = self.h1[name][np.asarray(broker_index < current_bucket)]
        if closed.empty: return

        signal = self.signals.evaluate(name, closed)
        if signal is None: return

        log(f"SIGNAL {name} {signal.direction.upper()} @AOI {signal.aoi_tf} {signal.aoi_price:.5f} "
            f"risk={signal.risk_pips}pips target={signal.target_rr}R (signal bar {signal.signal_time})")
        self._place(name, signal)

    def _place(self, name: str, signal: LiveSignal) -> None:
        # market order with relative stop and target in price points
        point = 10 ** (-self.symbol_meta[name]["digits"])
        sl_points = int(round(signal.risk / point))
        tp_points = int(round(signal.risk * signal.target_rr / point))
        volume = self._volume_for(name, signal)
        sides = self.sdk["ProtoOATradeSide"]
        side = sides.BUY if signal.direction == "long" else sides.SELL

        if self.dry_run or volume <= 0:
            log(f"  DRY_RUN would place {name} {signal.direction} vol={volume} SL={sl_points}pts TP={tp_points}pts")
            return

        request = self.sdk["ProtoOANewOrderReq"](
            ctidTraderAccountId=self.account_id, symbolId=self.symbol_ids[name],
            orderType=self.sdk["ProtoOAOrderType"].MARKET, tradeSide=side, volume=volume,
            relativeStopLoss=sl_points, relativeTakeProfit=tp_points)
        self._send(request, lambda response, n=name: log(f"  ORDER ack {n}"))

    def _volume_for(self, name: str, signal: LiveSignal) -> int:
        # fixed minimal size until balance and risk wiring is validated against the demo account
        return int(self.config.get("fixed_volume", DEFAULT_FIXED_VOLUME))

    def _schedule_heartbeat(self) -> None:
        self._heartbeat()
        self.sdk["reactor"].callLater(int(self.config.get("heartbeat_seconds", DEFAULT_HEARTBEAT_SECONDS)),
                                      self._schedule_heartbeat)

    def _heartbeat(self) -> None:
        log("--- heartbeat ---")
        for name in self.symbol_ids:
            if name not in self.h1 or self.h1[name].empty: continue
            try:
                log("  " + self.signals.state_line(name, self.h1[name]))
            except Exception as error:
                log(f"  {name} heartbeat err: {error}")

