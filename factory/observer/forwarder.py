"""AudaceFi forwarder (§17 topic 17) — mirrors ONE pair's confirmed freqtrade
position into AudaceFi long/flat signals. It never originates a decision: the
only thing it ever says is "the bot's confirmed position changed".

Shape: poll freqtrade's REST API (the poller's credentials), derive the
confirmed spot position for the single mapped pair, and when — and only when —
it differs from the last AudaceFi-confirmed state, emit one signal event
(`{id, sequence, symbol, side, targetBps, expiresAtMs}`) to the configured
sink: stdout JSON Lines (the kit's offline preview) or the kit's local HTTP
receiver. Everything ambiguous fails closed: an unreachable API, a bot not
running, a short or malformed position, a corrupt state file, or an
unresolved earlier signal each emit nothing.

State is one JSON file (`AUDACEFI_STATE`), written atomically BEFORE any send
(the kit's save-before-send rule), holding the last confirmed side, the
per-journal sequence, and the pending signal until a ranked receipt confirms
it. `forwarder.py init` creates it only after the operator asserts a
reconciled zero position — a missing file is never defaulted.

Env: FT_API_URL/FT_API_USER/FT_API_PASS (as the poller), AUDACEFI_PAIR
(freqtrade pair, e.g. ETH/USDT), AUDACEFI_SYMBOL (approved spot symbol),
AUDACEFI_TARGET_BPS, AUDACEFI_EXPIRY_S (<=60), AUDACEFI_STATE (file path),
AUDACEFI_EMIT (stdout|http), AUDACEFI_RECEIVER_PORT, AUDACEFI_RECEIVER_TOKEN
(http sink only; the token never appears in argv or logs).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from factory.observer import poller

SIDES = ("long", "flat")
SYMBOL_RE = re.compile(r"[A-Z0-9_-]{1,16}\Z")
ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")

# Receiver replies that leave the pending signal pending (retry next cycle).
HOLD = {"finality-pending", "ranking-pending", "busy"}
# Replies that stop the forwarder until an operator looks (pending kept).
HALT = {"review-required", "rejected", "unknown", "scope-mismatch", "closed-unranked"}


class Halt(Exception):
    """A condition the forwarder refuses to act past without an operator."""


# ---------------------------------------------------------------- position --

def position_from_snapshot(snap: dict, pair: str) -> str:
    """Confirmed spot position for one pair, from a poller snapshot.

    Returns "long" or "flat"; raises Halt on anything ambiguous. Other
    pairs' trades are ignored — the bot may trade many, we mirror one.
    """
    if not snap.get("ok"):
        raise Halt(f"freqtrade unreachable: {snap.get('error')}")
    if snap.get("state") != "running":
        raise Halt(f"bot state {snap.get('state')!r}, expected 'running'")
    rows = snap.get("status")
    if not isinstance(rows, list):
        raise Halt("status payload is not a list")
    mine = []
    for row in rows:
        if not isinstance(row, dict) or "pair" not in row:
            raise Halt("malformed status row")
        if row["pair"] != pair:
            continue
        if row.get("is_short"):
            raise Halt("short position needs operator review; spot has no mapping")
        if not row.get("is_open", True):
            continue
        amount = row.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise Halt(f"open trade with non-positive amount: {amount!r}")
        mine.append(row)
    if len(mine) > 1:
        raise Halt(f"{len(mine)} open trades on {pair}; expected at most one")
    return "long" if mine else "flat"


# ------------------------------------------------------------------ signal --

def build_signal(*, signal_id: str, sequence: int, symbol: str, side: str,
                 target_bps: int, expires_at_ms: int) -> bytes:
    """One signal event, validated against the kit's documented constraints."""
    if not ID_RE.fullmatch(signal_id):
        raise ValueError("signal id must be 8-64 URL-safe characters")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("sequence must be a positive integer")
    if not SYMBOL_RE.fullmatch(symbol) or symbol == "USDC":
        raise ValueError(f"not an approved spot symbol: {symbol!r}")
    if side not in SIDES:
        raise ValueError(f"side must be long or flat, got {side!r}")
    if side == "long" and not 1 <= target_bps <= 10_000:
        raise ValueError("a long needs targetBps in 1..10000")
    if side == "flat" and target_bps != 0:
        raise ValueError("a flat carries targetBps 0")
    if type(expires_at_ms) is not int or expires_at_ms <= 0:
        raise ValueError("expiresAtMs must be a positive integer")
    payload = json.dumps({
        "id": signal_id, "sequence": sequence, "symbol": symbol, "side": side,
        "targetBps": target_bps, "expiresAtMs": expires_at_ms,
    }, separators=(",", ":")).encode("ascii")
    if len(payload) > 512:
        raise ValueError("signal exceeds 512 bytes")
    return payload


# ------------------------------------------------------------------- state --

@dataclass
class State:
    confirmed: str                 # last AudaceFi-confirmed side
    sequence: int                  # last used sequence for this journal
    pending: dict | None           # {"side", "payload" (str), "run_scope"} | None
    path: Path

    @classmethod
    def init(cls, path: Path) -> "State":
        """Create the initial file; refuses to overwrite. The operator calling
        this asserts the AudaceFi position is a reconciled zero."""
        if path.exists():
            raise Halt(f"{path} exists — init never overwrites a journal state")
        state = cls(confirmed="flat", sequence=0, pending=None, path=path)
        state.save()
        return state

    @classmethod
    def load(cls, path: Path) -> "State":
        try:
            raw = json.loads(path.read_text())
            confirmed, sequence, pending = raw["confirmed"], raw["sequence"], raw["pending"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
            raise Halt(f"state file unreadable ({e!r}) — run init or restore it") from e
        pending_ok = pending is None or (
            isinstance(pending, dict)
            and pending.get("side") in SIDES
            and isinstance(pending.get("payload"), str))
        if confirmed not in SIDES or type(sequence) is not int or sequence < 0 \
                or not pending_ok:
            raise Halt("state file failed validation — restore it before forwarding")
        return cls(confirmed=confirmed, sequence=sequence, pending=pending, path=path)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"confirmed": self.confirmed,
                                   "sequence": self.sequence,
                                   "pending": self.pending}))
        tmp.replace(self.path)


# ------------------------------------------------------------------- cycle --

@dataclass
class Config:
    pair: str
    symbol: str
    target_bps: int
    expiry_s: int

    def __post_init__(self) -> None:
        if not 0 < self.expiry_s <= 60:
            raise ValueError("expiry must be within (0, 60] seconds")


def _settle(state: State, reply_status: str) -> dict:
    """Apply one transport reply to the pending signal. Fail-closed mapping."""
    pending = state.pending
    assert pending is not None
    if reply_status == "ranked":
        state.confirmed = pending["side"]
        state.pending = None
        state.save()
        return {"event": "confirmed", "side": state.confirmed}
    if reply_status in HOLD:
        return {"event": "pending", "reply": reply_status}
    # HALT statuses and anything unrecognized: keep the saved signal, stop.
    raise Halt(f"receiver replied {reply_status!r}; operator must inspect "
               "before any further signal")


def cycle(state: State, cfg: Config,
          read_snapshot: Callable[[], dict],
          send: Callable[[bytes], str],
          now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000) -> dict:
    """One forwarding cycle. Returns a report dict; emits at most one signal.

    Order: settle any pending signal first (same saved bytes — the kit treats
    a resend as reconciliation); only with nothing pending read freqtrade and
    forward a confirmed transition. Every refusal raises Halt upward.
    """
    if state.pending is not None:
        return _settle(state, send(state.pending["payload"].encode()))

    current = position_from_snapshot(read_snapshot(), cfg.pair)
    if current == state.confirmed:
        return {"event": "unchanged", "side": current}

    payload = build_signal(
        signal_id=f"fwd-{uuid.uuid4().hex[:24]}",
        sequence=state.sequence + 1, symbol=cfg.symbol, side=current,
        target_bps=cfg.target_bps if current == "long" else 0,
        expires_at_ms=now_ms() + cfg.expiry_s * 1000)
    # save-before-send: the journal knows the signal before the wire does.
    state.sequence += 1
    state.pending = {"side": current, "payload": payload.decode("ascii")}
    state.save()
    return _settle(state, send(payload))


# -------------------------------------------------------------------- sinks --

def send_stdout(payload: bytes) -> str:
    """Offline sink: print the event for the kit's preview; nothing confirms
    it, so it reports 'ranked' ONLY under AUDACEFI_EMIT=stdout where the
    operator accepts preview semantics (state advances optimistically)."""
    print(payload.decode("ascii"), flush=True)
    return "ranked"


def send_http(payload: bytes, *, port: int, token: str, run_scope: str) -> str:
    """POST one saved signal to the kit's local receiver; returns its status.

    Anything that is not a well-formed JSON reply maps to 'unknown' (halt).
    """
    import http.client
    if b"\n" in payload or b"\r" in payload or len(payload) > 512:
        raise ValueError("payload must be one line of at most 512 bytes")
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=65)
        try:
            conn.request("POST", "/signal", body=payload, headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Content-Length": str(len(payload)),
                "X-AudaceFi-Run-Scope": run_scope,
            })
            resp = conn.getresponse()
            body = resp.read(4096)
            reply = json.loads(body) if body else {}
            status = reply.get("status")
            if resp.status == 200 and status in {"ranked", "finality-pending",
                                                 "ranking-pending",
                                                 "review-required",
                                                 "closed-unranked"}:
                return status
            if resp.status == 429 and reply.get("code") == "SIGNAL_IN_PROGRESS":
                return "busy"
            if resp.status == 409 and reply.get("code") == "SIGNAL_RUN_SCOPE_MISMATCH":
                return "scope-mismatch"
            if status == "rejected":
                return "rejected"
            return "unknown"
        finally:
            conn.close()
    except (OSError, ValueError):
        return "unknown"


# --------------------------------------------------------------------- cli --

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="AudaceFi one-pair position forwarder")
    ap.add_argument("command", choices=["init", "once", "run"])
    args = ap.parse_args()

    state_path = Path(os.environ.get("AUDACEFI_STATE", "audacefi_state.json"))
    if args.command == "init":
        State.init(state_path)
        print(f"initialized {state_path} (confirmed=flat, sequence=0)")
        return

    cfg = Config(pair=os.environ["AUDACEFI_PAIR"],
                 symbol=os.environ["AUDACEFI_SYMBOL"],
                 target_bps=int(os.environ.get("AUDACEFI_TARGET_BPS", "2000")),
                 expiry_s=int(os.environ.get("AUDACEFI_EXPIRY_S", "55")))

    def read_snapshot() -> dict:
        base = os.environ.get("FT_API_URL", "http://127.0.0.1:8080")
        return poller.snapshot(base, os.environ.get("FT_API_USER", "freqtrader"),
                               os.environ.get("FT_API_PASS", ""))

    if os.environ.get("AUDACEFI_EMIT", "stdout") == "http":
        port = int(os.environ["AUDACEFI_RECEIVER_PORT"])
        token = os.environ["AUDACEFI_RECEIVER_TOKEN"]
        scope = os.environ["AUDACEFI_RUN_SCOPE"]
        send = lambda p: send_http(p, port=port, token=token, run_scope=scope)  # noqa: E731
    else:
        send = send_stdout

    interval = int(os.environ.get("OBS_INTERVAL_SECS", "300"))
    while True:
        state = State.load(state_path)
        try:
            report = cycle(state, cfg, read_snapshot, send)
        except Halt as halt:
            report = {"event": "halt", "reason": str(halt)}
        print(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **report}),
              flush=True)
        if args.command == "once" or report["event"] == "halt":
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
