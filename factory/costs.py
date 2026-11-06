"""The cost model — one home for what a trade costs and how much edge
covers it.

Fee basis (per-side), round-trip, the 3x required multiple (Plan §12/§14
R3), the turnover scaling (Plan §17.10) and the S5 sweep grid live here.
S2, S4 and S5 ask this module one question instead of each re-deciding fee
basis, round-trip, multiple and turnover — which is how S5 once re-judged
a 10%-turnover tilt as if it paid a full round trip.

The bash parity loop (factory/observer/parity_loop.sh) cannot import
Python: it takes FEE from the environment, whose default mirrors
WORKING.fee_per_side. Change one, change the other.
"""

from __future__ import annotations

from dataclasses import dataclass

from factory.gates import core
from factory.gates.core import GateVerdict


@dataclass(frozen=True)
class CostModel:
    fee_per_side: float = 0.001     # the working fee basis
    required_multiple: float = 3.0  # Plan §12/§14 R3
    # S5's cost sweep; must contain 0.0 (zero-fee sanity) and the working fee
    sweep_fees: tuple = (0.0, 0.0005, 0.001, 0.002, 0.003)

    def __post_init__(self):
        if 0.0 not in self.sweep_fees:
            raise ValueError("sweep_fees must include 0.0 (zero-fee sanity)")
        if self.fee_per_side not in self.sweep_fees:
            raise ValueError("sweep_fees must include the working fee")

    @property
    def roundtrip(self) -> float:
        return 2 * self.fee_per_side

    def edge_gate(self, claimed_edge: float) -> float:
        """Resolution target (Plan §17.10): the smaller of the claimed edge
        and the full-round-trip 3x edge. For turnover-1 cards this is always
        the 3x edge (a claim below it dies at cost coverage anyway); for
        cheap rebalancing tilts the testability question becomes the claim
        itself."""
        return min(claimed_edge, self.required_multiple * self.roundtrip)

    def coverage(self, gross_edge_per_trade: float,
                 turnover_per_trade: float = 1.0) -> GateVerdict:
        """The 3x rule against this model's round trip, scaled to what the
        trade actually transacts."""
        return core.cost_coverage(gross_edge_per_trade, self.roundtrip,
                                  self.required_multiple, turnover_per_trade)


WORKING = CostModel()
