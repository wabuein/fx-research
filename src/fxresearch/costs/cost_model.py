from __future__ import annotations

from dataclasses import dataclass

# round trip cost = measured dukascopy mean bid-ask spread in pips, 2023-2026 h1
ROUND_TRIP_COST_PIPS = {
    "EURUSD": 0.52,
    "GBPUSD": 1.23,
    "AUDUSD": 1.21,
    "NZDUSD": 1.35,
    "USDCAD": 1.57,
    "USDJPY": 1.00,
    "EURGBP": 1.23,
    "EURJPY": 1.67,
    "GBPJPY": 2.98,
    "AUDJPY": 1.41,
    "NZDJPY": 1.86,
    "GBPCHF": 2.85,
    "AUDCHF": 2.14,
    "NZDCAD": 3.10,
    # metals and commodity cfds, pip: xau 0.1, xag 0.01, xpt 0.1, copper 0.0005
    "XAUUSD": 5.19,
    "XAGUSD": 4.05,
    "XPTUSD": 27.33,
    "COPPER": 8.42,
}
DEFAULT_COST_PIPS = 1.5

# raw account: $3.5 per side per lot = $7 round trip per 100k, converted to pips via the usd pip value
COMMISSION_PIPS = {
    "EURUSD": 0.70, "GBPUSD": 0.70, "AUDUSD": 0.70, "NZDUSD": 0.70,
    "USDCAD": 0.95, "USDJPY": 1.05,
    "EURGBP": 0.55, "EURJPY": 1.05, "GBPJPY": 1.05, "AUDJPY": 1.05,
    "NZDJPY": 1.05, "GBPCHF": 0.63, "AUDCHF": 0.63, "NZDCAD": 0.95,
    "XAUUSD": 0.70, "XAGUSD": 0.70, "XPTUSD": 0.70, "COPPER": 0.70,
}
DEFAULT_COMMISSION_PIPS = 0.80

# raw accounts pass the spread through with a small markup
RAZOR_SPREAD_MULT = 1.1

STANDARD = "standard"
RAW = "raw"


@dataclass(frozen=True)
class CostRow:

    spread_pips: float
    commission_pips: float


DEFAULT_ROW = CostRow(DEFAULT_COST_PIPS, DEFAULT_COMMISSION_PIPS)


class CostModel:

    def __init__(self, spreads: dict[str, float] = ROUND_TRIP_COST_PIPS,
                 commissions: dict[str, float] = COMMISSION_PIPS) -> None:
        self.spreads = spreads
        self.commissions = commissions

        self.rows: dict[str, CostRow] = {}
        self.load()

    def load(self) -> None:
        instruments = list(self.spreads) + [i for i in self.commissions if i not in self.spreads]
        self.rows = {
            instrument: CostRow(self.spreads.get(instrument, DEFAULT_COST_PIPS),
                                self.commissions.get(instrument, DEFAULT_COMMISSION_PIPS))
            for instrument in instruments
        }

    def get_row(self, instrument: str) -> CostRow:
        return self.rows.get(instrument, DEFAULT_ROW)

    def cost_r(self, instrument: str, risk_pips: float, mult: float = 1.0, account: str = STANDARD) -> float:
        if risk_pips is None or risk_pips <= 0: return 0.0

        row = self.get_row(instrument)
        if account == RAW:
            # mult stresses only the spread, the commission is a fixed pip cost
            cost_pips = row.spread_pips * RAZOR_SPREAD_MULT * mult + row.commission_pips
        else:
            cost_pips = row.spread_pips * mult

        return cost_pips / risk_pips

