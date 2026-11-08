"""The universe registry — Plan §17 topic 13.

LEGACY_17 is the original registered universe: every battery, fixture and
regression arm before topic 13 ran on it, and the topic 11/13 regression
arms must keep running on it bit-for-bit, so it lives here as a constant
and is imported wherever it used to be hardcoded.

The EXPANDED universe is data, not code: `tools/build_universe.py` applies
the pre-committed rule (enumerate Binance Vision spot *USDT symbols —
delisted included; exclude stable/fiat bases, leveraged tokens, wrapped
pegs; first month <= 2023-12; >= 24 monthly files <= 2025-12; median daily
quote volume >= US$10M over the name's own last 365 available days; top 80
by that median if more qualify; union with LEGACY_17) and writes
`universe_expanded.json` beside this module with the per-name evidence.
Point-in-time membership needs no machinery here: a name is NaN outside
its listed life and the screen seams are pairwise-valid.
"""

from __future__ import annotations

import json
from pathlib import Path

LEGACY_17 = ["ADA", "ALGO", "AVAX", "BNB", "BTC", "DOGE", "ETH", "HBAR",
             "LINK", "LTC", "NEAR", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC"]

EXPANDED_JSON = Path(__file__).resolve().parent / "universe_expanded.json"


def expanded_meta() -> dict:
    """{symbol: {first_month, last_month, months, median_quote_vol_usd}}."""
    return json.loads(EXPANDED_JSON.read_text())["symbols"]


def expanded() -> list[str]:
    """The expanded universe, sorted; raises if the JSON was never built."""
    return sorted(expanded_meta())


def known() -> set[str]:
    """Every base name a card may put in its universe: the legacy 17 plus
    the expanded registry when it has been built. A name outside this set
    has no vetted data behind it and is rejected at intake."""
    base = set(LEGACY_17)
    try:
        base |= set(expanded_meta())
    except FileNotFoundError:
        pass
    return base


# --- Plan §17 topic 16: the universe descriptor -----------------------------
# Data generality as a seam, not speculative ingestion: a universe carries its
# own panel registry (each panel's one-sentence causality contract — the
# dsl.py funding comment, generalized — and a level-safety flag), calendar,
# annualization factor and cost metadata. Sole instances today are
# crypto-binance; a new asset class arrives as a new descriptor + loader +
# its own data-vetting registration, never as edits to the screens.

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PanelSpec:
    """One panel's contract. `level_safe=False` is the futures lesson bought
    early: on a back-adjusted continuous series returns are meaningful and
    LEVELS are not, so such a panel is usable only as the direct first
    argument of ts_ret — enforced by dsl.validate_for_universe."""
    causality: str
    level_safe: bool = True


@dataclass(frozen=True)
class UniverseDescriptor:
    name: str
    symbols: tuple[str, ...]
    panels: dict = field(default_factory=dict)
    calendar: str = "24/7"
    ann_factor: int = 365
    taker_cost_bps: float = 10.0


_CRYPTO_PANELS = {
    "close": PanelSpec("daily close at t, known at t"),
    "volume": PanelSpec("volume over the day ending at t"),
    "funding": PanelSpec("the day's 8h funding events, all settled before "
                         "the daily close at t"),
}


def crypto_binance_legacy17() -> UniverseDescriptor:
    return UniverseDescriptor(name="crypto-binance-legacy17",
                              symbols=tuple(LEGACY_17),
                              panels=dict(_CRYPTO_PANELS))


def crypto_binance_expanded() -> UniverseDescriptor:
    return UniverseDescriptor(name="crypto-binance-expanded",
                              symbols=tuple(expanded()),
                              panels=dict(_CRYPTO_PANELS))
