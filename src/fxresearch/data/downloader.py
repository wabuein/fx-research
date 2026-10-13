from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from fxresearch.data.dukascopy import DukascopyHandler
from fxresearch.data.instruments import DUKA_SYMBOLS

NPX_PACKAGE = "dukascopy-node@latest"
ATTEMPTS = 3
START_SLACK_DAYS = 30
END_SLACK_DAYS = 7


@dataclass
class DownloadResult:

    instrument: str
    tf: str
    ok: bool
    message: str


class DukascopyDownloader:

    def __init__(self, data: DukascopyHandler, price: str = "bid") -> None:
        self.price = price

        self.data = data

    def download_all(self, instruments: list[str], timeframes: list[str], date_from: str, date_to: str,
                     skip_existing: bool) -> list[DownloadResult]:
        results = []

        for instrument in instruments:
            for tf in timeframes:
                if skip_existing and self.has_coverage(instrument, tf, date_from, date_to):
                    results.append(DownloadResult(instrument, tf, True, "already covers range"))
                    continue

                ok, message = self.download_one(instrument, tf, date_from, date_to)
                results.append(DownloadResult(instrument, tf, ok, message))

        return results

    def download_one(self, instrument: str, tf: str, date_from: str, date_to: str) -> tuple[bool, str]:
        code = DUKA_SYMBOLS[instrument]
        last_note = ""

        for attempt in range(1, ATTEMPTS + 1):
            df, note = self._attempt(code, tf, date_from, date_to)
            if df is None:
                last_note = note
                continue

            self._staged_path(code, tf).replace(self.out_path(instrument, tf))
            ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            retry = f" (after {attempt} tries)" if attempt > 1 else ""
            return True, f"{len(df):>7} rows  {ts.min().date()} -> {ts.max().date()}{retry}"

        return False, f"failed after {ATTEMPTS} attempts: {last_note}"

    def has_coverage(self, instrument: str, tf: str, date_from: str, date_to: str) -> bool:
        path = self.out_path(instrument, tf)
        if not path.exists() or path.stat().st_size < 200: return False

        try:
            df = pd.read_csv(path)
            ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        except Exception:
            return False

        return self._covers(ts, date_from, date_to)

    def out_path(self, instrument: str, tf: str) -> Path:
        if self.price == "bid": return self.data.csv_path(instrument, tf)
        return self.data.ask_path(instrument, tf)

    def _attempt(self, code: str, tf: str, date_from: str, date_to: str) -> tuple[pd.DataFrame | None, str]:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(self._command(code, tf, date_from, date_to, tmp), capture_output=True, text=True)

            produced = sorted(Path(tmp).glob("*.csv"))
            if not produced:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-2:]
                return None, f"no file ({' | '.join(tail)})"

            try:
                df = pd.read_csv(produced[0])
            except pd.errors.EmptyDataError:
                return None, "empty csv"
            if df.empty: return None, "empty series"

            ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            if not self._covers(ts, date_from, date_to):
                return None, f"incomplete coverage ({ts.min().date()} -> {ts.max().date()})"

            # move the file out before the temporary directory is removed
            self.data.data_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(produced[0]), str(self._staged_path(code, tf)))
            return df, ""

    def _command(self, code: str, tf: str, date_from: str, date_to: str, out_dir: str) -> list[str]:
        return [
            "npx", "--yes", NPX_PACKAGE,
            "-i", code,
            "-from", date_from,
            "-to", date_to,
            "-t", tf,
            "-p", self.price,
            "-f", "csv",
            "-dir", out_dir,
            "-r", "5",
            "-rp", "1500",
            "-bs", "30",
            "-bp", "200",
            "-v", "false",
        ]

    def _staged_path(self, code: str, tf: str) -> Path:
        return self.data.data_dir / f".{code}_{tf}_{self.price}.tmp.csv"

    def _covers(self, ts: pd.Series, date_from: str, date_to: str) -> bool:
        want_from = pd.Timestamp(date_from, tz="UTC")
        want_to = pd.Timestamp(date_to, tz="UTC")
        return (ts.min() <= want_from + pd.Timedelta(days=START_SLACK_DAYS)
                and ts.max() >= want_to - pd.Timedelta(days=END_SLACK_DAYS))

