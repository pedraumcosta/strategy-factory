"""Purged, embargoed walk-forward splitter — U1's deliverable (Plan §8,
López de Prado ch. 7).

The lab's wf/run.sh folds end the in-sample window exactly where the
out-of-sample window begins. A trade opened near the boundary closes inside
OOS, so its label is computed on OOS data and the in-sample optimizer sees
it: label leakage. **Purging** removes the last `purge_days` from each
training window, sized at or above the strategy's maximum holding period, so
no training label can span the boundary.

**Embargo** refuses training windows that begin within `embargo_days` AFTER
any test window (serial correlation leaks backward from an evaluated test
set into training data that immediately follows it, once the researcher has
iterated on those test results). This is NOT inert for the lab's rolling
folds: folds 5-7 begin training exactly one day after folds 1-3's test
windows end, so wf/run.sh violates even a one-day embargo — measured by
test_lab_rolling_folds_violate_the_embargo. A training window that wholly
CONTAINS an earlier test window is ordinary walk-forward reuse of past data
and is not flagged; only starting inside the post-test embargo is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Fold:
    n: int
    train_start: date
    train_end: date  # exclusive
    test_start: date  # exclusive gap [train_end, test_start) is the purge
    test_end: date

    @property
    def purge_gap_days(self) -> int:
        return (self.test_start - self.train_end).days

    def train_timerange(self) -> str:
        return f"{self.train_start:%Y%m%d}-{self.train_end:%Y%m%d}"

    def test_timerange(self) -> str:
        return f"{self.test_start:%Y%m%d}-{self.test_end:%Y%m%d}"


class SplitError(ValueError):
    pass


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _check(folds: list[Fold], purge_days: int, embargo_days: int) -> list[Fold]:
    for f in folds:
        if not (f.train_start < f.train_end <= f.test_start < f.test_end):
            raise SplitError(f"fold {f.n} is not ordered: {f}")
        if f.purge_gap_days < purge_days:
            raise SplitError(
                f"fold {f.n}: purge gap {f.purge_gap_days}d < required {purge_days}d"
            )
    # Embargo invariant: no training window may START inside
    # (test_end, test_end + embargo] of any OTHER fold's test window.
    for f in folds:
        for g in folds:
            if g is f:
                continue
            lo, hi = g.test_end, g.test_end + timedelta(days=embargo_days)
            if lo < f.train_start <= hi:
                raise SplitError(
                    f"fold {f.n} training starts {f.train_start} inside the "
                    f"{embargo_days}d embargo after fold {g.n}'s test end {lo}"
                )
    return folds


def purge_existing(
    folds_json: dict,
    purge_days: int,
    embargo_days: int = 0,
) -> list[Fold]:
    """Purge the lab's recorded walk-forward folds (walkforward.json format):
    identical test (OOS) windows — results stay comparable fold-for-fold —
    with each training (IS) window's end pulled back `purge_days`. Purging
    removes data; it does not shift the window, so the training set shrinks
    by exactly the purge."""
    out = []
    for f in folds_json["folds"]:
        is_start, is_end = (_d(x) for x in f["is"].split("-"))
        oos_start, oos_end = (_d(x) for x in f["oos"].split("-"))
        if is_end != oos_start:
            raise SplitError(
                f"fold {f['fold']}: expected contiguous IS/OOS, got {f['is']} / {f['oos']}"
            )
        out.append(Fold(
            n=f["fold"],
            train_start=is_start,
            train_end=oos_start - timedelta(days=purge_days),
            test_start=oos_start,
            test_end=oos_end,
        ))
    return _check(out, purge_days, embargo_days)


def purged_walkforward(
    start: str,
    end: str,
    n_folds: int,
    train_days: int,
    test_days: int,
    purge_days: int,
    embargo_days: int = 0,
) -> list[Fold]:
    """Generate rolling purged folds from scratch: consecutive test windows
    tiling forward from `start + train_days + purge_days`, each preceded by a
    `train_days` window that ends `purge_days` before the test begins."""
    s, e = _d(start), _d(end)
    folds = []
    test_start = s + timedelta(days=train_days + purge_days)
    for k in range(1, n_folds + 1):
        test_end = test_start + timedelta(days=test_days)
        if test_end > e:
            raise SplitError(
                f"fold {k} test window ends {test_end}, past the data end {e}"
            )
        train_end = test_start - timedelta(days=purge_days)
        folds.append(Fold(
            n=k,
            train_start=train_end - timedelta(days=train_days),
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
        ))
        test_start = test_end
    return _check(folds, purge_days, embargo_days)
