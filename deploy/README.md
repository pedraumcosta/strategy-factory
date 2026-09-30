# deploy/ — the S6 stack (dry-run ONLY)

`docker-compose.yaml` runs three services: **freqtrade** (dry-run, Binance
public data, FreqUI/API on localhost:8080), **observer** (5-min snapshots to
`observer_data/snapshots.jsonl`, Telegram alerts on unreachable/not-running),
and **parity** (daily: backtest the elapsed window, compare with the dry-run
DB, write `observer_data/parity_report.md` — Plan §6 Phase 3 gate (d)).

- Local rehearsal: `cp .env.example .env`, set `FT_IMAGE=freqtrade-lab:2026.8`,
  `docker compose up -d`. Tear down with `docker compose down`.
- GCP: `PROJECT=<id> bash gcp/provision.sh` (see the script header; ~$13/mo).
- The bundled strategy is a **killed rehearsal strategy** (see its banner).
  A real deployment replaces `strategy/` with a gate-passed run's artifact
  and requires a signed HG3.
- No exchange keys exist anywhere in this stack; `.env` holds only the API
  password and JWT secret, and is gitignored.
