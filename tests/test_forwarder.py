"""Forwarder (§17 topic 17): confirmed transitions in, at most one signal out,
everything ambiguous fails closed."""

import json

import pytest

from factory.observer import forwarder
from factory.observer.forwarder import Config, Halt, State


def snap(rows, ok=True, state="running", error=None):
    out = {"ok": ok, "state": state, "status": rows}
    if error:
        out["error"] = error
    return out


def trade(pair, amount=1.5, is_open=True, is_short=False):
    return {"pair": pair, "amount": amount, "is_open": is_open, "is_short": is_short}


CFG = Config(pair="ETH/USDT", symbol="TEST", target_bps=2000, expiry_s=55)


def new_state(tmp_path):
    return State.init(tmp_path / "state.json")


# ---------------------------------------------------------------- position --

def test_position_flat_on_empty_ok_snapshot():
    assert forwarder.position_from_snapshot(snap([]), "ETH/USDT") == "flat"


def test_position_long_on_one_open_trade_ignoring_other_pairs():
    rows = [trade("BTC/USDT"), trade("ETH/USDT"), trade("SOL/USDT")]
    assert forwarder.position_from_snapshot(snap(rows), "ETH/USDT") == "long"


def test_position_closed_trade_rows_do_not_count():
    rows = [trade("ETH/USDT", is_open=False)]
    assert forwarder.position_from_snapshot(snap(rows), "ETH/USDT") == "flat"


@pytest.mark.parametrize("bad", [
    snap([], ok=False, error="conn refused"),
    snap([], state="stopped"),
    snap(None),
    snap([{"amount": 1}]),                                  # row without pair
    snap([trade("ETH/USDT", is_short=True)]),               # short needs review
    snap([trade("ETH/USDT", amount=0)]),                    # non-positive amount
    snap([trade("ETH/USDT"), trade("ETH/USDT")]),           # duplicate opens
])
def test_position_fails_closed_on_ambiguity(bad):
    with pytest.raises(Halt):
        forwarder.position_from_snapshot(bad, "ETH/USDT")


# ------------------------------------------------------------------ signal --

def test_signal_shape_and_constraints():
    raw = forwarder.build_signal(signal_id="fwd-12345678", sequence=1,
                                 symbol="TEST", side="long", target_bps=2000,
                                 expires_at_ms=1_700_000_000_000)
    event = json.loads(raw)
    assert set(event) == {"id", "sequence", "symbol", "side", "targetBps",
                          "expiresAtMs"}
    assert len(raw) <= 512 and b"\n" not in raw


@pytest.mark.parametrize("kw", [
    dict(signal_id="short"),                      # id too short
    dict(side="short"),                           # no shorts, ever
    dict(side="flat", target_bps=100),            # flat carries 0
    dict(target_bps=0),                           # long needs positive bps
    dict(target_bps=10_001),                      # above cap
    dict(symbol="USDC"),                          # quote is not a target
    dict(symbol="eth"),                           # symbol charset
    dict(sequence=0),                             # sequence starts at 1
])
def test_signal_rejects_bad_fields(kw):
    base = dict(signal_id="fwd-12345678", sequence=1, symbol="TEST",
                side="long", target_bps=2000, expires_at_ms=1_700_000_000_000)
    with pytest.raises(ValueError):
        forwarder.build_signal(**{**base, **kw})


# ------------------------------------------------------------------- state --

def test_state_init_refuses_overwrite(tmp_path):
    State.init(tmp_path / "s.json")
    with pytest.raises(Halt):
        State.init(tmp_path / "s.json")


def test_state_missing_or_corrupt_fails_closed(tmp_path):
    with pytest.raises(Halt):
        State.load(tmp_path / "absent.json")
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(Halt):
        State.load(tmp_path / "bad.json")
    (tmp_path / "badpending.json").write_text(json.dumps(
        {"confirmed": "flat", "sequence": 1, "pending": {"side": "up"}}))
    with pytest.raises(Halt):
        State.load(tmp_path / "badpending.json")


# ------------------------------------------------------------------- cycle --

def run_cycle(state, rows, send, **kw):
    return forwarder.cycle(state, CFG, lambda: snap(rows), send,
                           now_ms=kw.get("now_ms", lambda: 1_700_000_000_000))


def test_unchanged_position_emits_nothing(tmp_path):
    state = new_state(tmp_path)
    sent = []
    report = run_cycle(state, [], sent.append)
    assert report == {"event": "unchanged", "side": "flat"} and sent == []


def test_transition_emits_one_signal_and_ranked_advances(tmp_path):
    state = new_state(tmp_path)
    sent = []

    def send(payload):
        sent.append(json.loads(payload))
        # save-before-send: the pending signal is on disk before the wire call
        on_disk = json.loads(state.path.read_text())
        assert on_disk["pending"]["side"] == "long"
        return "ranked"

    report = run_cycle(state, [trade("ETH/USDT")], send)
    assert report == {"event": "confirmed", "side": "long"}
    assert len(sent) == 1 and sent[0]["side"] == "long" and sent[0]["sequence"] == 1
    assert sent[0]["targetBps"] == 2000
    # and back: flat transition
    report = run_cycle(state, [], lambda p: "ranked")
    assert report == {"event": "confirmed", "side": "flat"}
    reloaded = State.load(state.path)
    assert reloaded.confirmed == "flat" and reloaded.sequence == 2


def test_expiry_comes_from_clock_and_config(tmp_path):
    state = new_state(tmp_path)
    seen = []

    def send(payload):
        seen.append(json.loads(payload))
        return "ranked"

    run_cycle(state, [trade("ETH/USDT")], send, now_ms=lambda: 1_000_000)
    assert seen[0]["expiresAtMs"] == 1_000_000 + 55_000


def test_pending_blocks_new_signals_until_ranked(tmp_path):
    state = new_state(tmp_path)
    report = run_cycle(state, [trade("ETH/USDT")], lambda p: "finality-pending")
    assert report == {"event": "pending", "reply": "finality-pending"}
    # next cycle resends the SAME saved bytes, no new signal even on change
    resent = []

    def send(payload):
        resent.append(json.loads(payload))
        return "ranked"

    state2 = State.load(state.path)
    report = run_cycle(state2, [], send)       # position flipped back meanwhile
    assert report == {"event": "confirmed", "side": "long"}
    assert resent[0]["sequence"] == 1          # the original signal, not a new one


def test_halt_statuses_keep_pending_and_stop(tmp_path):
    state = new_state(tmp_path)
    with pytest.raises(Halt):
        run_cycle(state, [trade("ETH/USDT")], lambda p: "rejected")
    reloaded = State.load(state.path)
    assert reloaded.pending is not None and reloaded.confirmed == "flat"
    # still halted next cycle; nothing new is prepared
    with pytest.raises(Halt):
        run_cycle(reloaded, [trade("ETH/USDT")], lambda p: "unknown")


def test_sequence_monotonic_across_restarts(tmp_path):
    state = new_state(tmp_path)
    ids = []

    def send(payload):
        ids.append(json.loads(payload))
        return "ranked"

    run_cycle(state, [trade("ETH/USDT")], send)
    state = State.load(state.path)             # simulated restart
    run_cycle(state, [], send)
    state = State.load(state.path)
    run_cycle(state, [trade("ETH/USDT")], send)
    assert [e["sequence"] for e in ids] == [1, 2, 3]
    assert len({e["id"] for e in ids}) == 3
