"""Record the golden reference backtest (run once; the fixture is then law).

The reference is the lab README's canonical command: XSMomentum, 1d,
20210101-20260101, fee 0.001, --cache none. That window is spent research
data (Plan §18.2) — replication spends nothing.
"""

import json
from pathlib import Path

from factory.engine.lab import LabEngine

SPEC = {
    "strategy": "XSMomentum",
    "timeframe": "1d",
    "timerange": "20210101-20260101",
    "fee": 0.001,
}

if __name__ == "__main__":
    result = LabEngine().backtest(**SPEC)
    out = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "reference.json"
    out.write_text(json.dumps({"spec": SPEC, "expect": result.to_fixture()}, indent=1))
    print(f"recorded {result.trade_count} trades, "
          f"profit_total_abs={result.profit_total_abs!r} -> {out}")
