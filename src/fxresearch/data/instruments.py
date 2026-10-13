from __future__ import annotations

# internal instrument name -> dukascopy-node instrument code, in research order
DUKA_SYMBOLS = {
    "AUDUSD": "audusd",
    "EURGBP": "eurgbp",
    "EURJPY": "eurjpy",
    "GBPCHF": "gbpchf",
    "AUDCHF": "audchf",
    "AUDJPY": "audjpy",
    "GBPJPY": "gbpjpy",
    "EURUSD": "eurusd",
    "GBPUSD": "gbpusd",
    "NZDCAD": "nzdcad",
    "NZDJPY": "nzdjpy",
    "NZDUSD": "nzdusd",
    "USDCAD": "usdcad",
    "USDJPY": "usdjpy",
    "XAUUSD": "xauusd",
    "XAGUSD": "xagusd",
    "XPTUSD": "xptcmdusd",
    "COPPER": "coppercmdusd",
}

PIP_SIZE = {
    "AUDUSD": 0.0001,
    "EURGBP": 0.0001,
    "EURJPY": 0.01,
    "GBPCHF": 0.0001,
    "AUDCHF": 0.0001,
    "AUDJPY": 0.01,
    "GBPJPY": 0.01,
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "NZDCAD": 0.0001,
    "NZDJPY": 0.01,
    "NZDUSD": 0.0001,
    "USDCAD": 0.0001,
    "USDJPY": 0.01,
    "XAUUSD": 0.1,
    "XAGUSD": 0.01,
    "XPTUSD": 0.1,
    "COPPER": 0.0005,
}

DEFAULT_PIP_SIZE = 0.0001

# the 12 fx pairs kept after dropping metals, copper, nzdcad and audchf on spread cost alone
KEEP12 = [
    "AUDUSD", "EURUSD", "EURGBP", "NZDJPY", "EURJPY", "USDJPY",
    "GBPUSD", "USDCAD", "AUDJPY", "GBPJPY", "GBPCHF", "NZDUSD",
]


def pip_size(instrument: str) -> float:
    return PIP_SIZE.get(instrument, DEFAULT_PIP_SIZE)


def parse_instruments(value: str | None) -> list[str]:
    if not value: return []
    return [item.strip() for item in value.split(",") if item.strip()]
