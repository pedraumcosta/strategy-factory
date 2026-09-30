"""The splitter's invariants, and the purge applied to the lab's real folds."""

import json
from pathlib import Path

import pytest

from factory.validation import splitter

ROOT = Path(__file__).resolve().parents[1]
WF = json.loads((ROOT / "lab" / "user_data" / "notebooks" / "walkforward.json").read_text())


def test_lab_folds_are_contiguous_hence_leaky():
    """The premise of U1: every recorded fold has IS end == OOS start."""
    for f in WF["folds"]:
        assert f["is"].split("-")[1] == f["oos"].split("-")[0]


def test_purge_existing_keeps_test_windows_and_trims_train():
    folds = splitter.purge_existing(WF, purge_days=30)
    assert len(folds) == 7
    for f, orig in zip(folds, WF["folds"]):
        assert f.test_timerange() == orig["oos"]          # OOS unchanged
        assert f.purge_gap_days == 30                     # gap exists
        assert f.train_timerange() != orig["is"]          # IS trimmed
        assert f.train_start.strftime("%Y%m%d") == orig["is"].split("-")[0]


def test_zero_purge_is_refused_when_required():
    with pytest.raises(splitter.SplitError, match="purge gap"):
        folds = splitter.purge_existing(WF, purge_days=0)
        splitter._check(folds, purge_days=1, embargo_days=0)


def test_generated_folds_tile_and_respect_purge():
    # 540 + 30 + 7*180 = 1830 days of span needed
    folds = splitter.purged_walkforward(
        "20210101", "20260206", n_folds=7,
        train_days=540, test_days=180, purge_days=30,
    )
    assert len(folds) == 7
    for a, b in zip(folds, folds[1:]):
        assert a.test_end == b.test_start                 # tests tile
    for f in folds:
        assert f.purge_gap_days == 30
        assert (f.train_end - f.train_start).days == 540


def test_generated_folds_refuse_to_run_past_data_end():
    with pytest.raises(splitter.SplitError, match="past the data end"):
        splitter.purged_walkforward(
            "20210101", "20230101", n_folds=7,
            train_days=540, test_days=180, purge_days=30,
        )


def test_lab_rolling_folds_violate_the_embargo():
    """A finding, not a formality: with rolling 18-month IS windows, folds
    5-7 begin training exactly one day after folds 1-3's test windows end.
    The recorded splitter fails even a one-day embargo."""
    with pytest.raises(splitter.SplitError, match="embargo"):
        splitter.purge_existing(WF, purge_days=30, embargo_days=1)
    splitter.purge_existing(WF, purge_days=30, embargo_days=0)  # purge alone: ok


def test_embargo_catches_a_reversed_split():
    from datetime import date
    bad = [
        splitter.Fold(1, date(2021, 1, 1), date(2022, 1, 1),
                      date(2022, 2, 1), date(2022, 8, 1)),
        # fold 2 trains starting 10 days after fold 1's test ends
        splitter.Fold(2, date(2022, 8, 11), date(2023, 8, 1),
                      date(2023, 9, 1), date(2024, 3, 1)),
    ]
    with pytest.raises(splitter.SplitError, match="embargo"):
        splitter._check(bad, purge_days=28, embargo_days=30)
    splitter._check(bad, purge_days=28, embargo_days=5)  # smaller embargo: fine
