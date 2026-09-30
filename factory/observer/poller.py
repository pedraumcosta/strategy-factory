"""S7 observer — polls a running freqtrade's REST API and appends one
JSON line per cycle to an append-only snapshot log.

Stdlib only (urllib), so it runs in a bare python container next to the
bot. What it watches: bot state, open trades, profit, balance, whitelist.
Alerts (Telegram, env-configured) fire when the API is unreachable or the
bot is not running — silence is not success, so the poller writes a
snapshot line even on failure.

Env: FT_API_URL (default http://127.0.0.1:8080), FT_API_USER, FT_API_PASS,
TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (both optional), OBS_INTERVAL_SECS.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINTS = ["status", "profit", "balance", "count", "whitelist", "show_config"]


def _get(base: str, path: str, token: str, timeout: int = 15):
    req = urllib.request.Request(f"{base}/api/v1/{path}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def login(base: str, user: str, password: str, timeout: int = 15) -> str:
    cred = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(f"{base}/api/v1/token/login", method="POST")
    req.add_header("Authorization", f"Basic {cred}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["access_token"]


def snapshot(base: str, user: str, password: str) -> dict:
    """One poll cycle. Never raises: failures are data too."""
    out: dict = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "ok": False}
    try:
        token = login(base, user, password)
        for ep in ENDPOINTS:
            out[ep] = _get(base, ep, token)
        out["ok"] = True
        out["state"] = out.get("show_config", {}).get("state")
        out["open_trades"] = len(out.get("status") or [])
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError) as e:
        out["error"] = str(e)
    return out


def problems(snap: dict) -> list[str]:
    if not snap["ok"]:
        return [f"freqtrade API unreachable: {snap.get('error')}"]
    if snap.get("state") != "running":
        return [f"bot state is {snap.get('state')!r}, expected 'running'"]
    return []


def alert(msg: str) -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    print(f"ALERT: {msg}", flush=True)
    if not (token and chat):
        return
    try:
        data = json.dumps({"chat_id": chat, "text": f"[observer] {msg}"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except (urllib.error.URLError, OSError):
        print("ALERT delivery failed (Telegram unreachable)", flush=True)


def run_once(out_dir: Path) -> dict:
    base = os.environ.get("FT_API_URL", "http://127.0.0.1:8080")
    snap = snapshot(base, os.environ.get("FT_API_USER", "freqtrader"),
                    os.environ.get("FT_API_PASS", ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "snapshots.jsonl", "a") as f:
        f.write(json.dumps(snap) + "\n")
    for p in problems(snap):
        alert(p)
    return snap


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="observer_data")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    interval = int(os.environ.get("OBS_INTERVAL_SECS", "300"))
    while True:
        snap = run_once(Path(args.out))
        print(json.dumps({k: snap.get(k) for k in
                          ("at", "ok", "state", "open_trades", "error")}),
              flush=True)
        if args.once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
