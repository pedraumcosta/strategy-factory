#!/bin/bash
# Provision the factory's dry-run box on GCP (S6). One VM, no public ports;
# FreqUI is reached through an SSH tunnel. Idempotent-ish: safe to re-read,
# not to blind-rerun. COSTS MONEY (e2-small ~US$13/mo) — run deliberately.
#
# Usage: PROJECT=<gcp-project> ZONE=us-central1-a bash provision.sh
set -euo pipefail
PROJECT="${PROJECT:?set PROJECT}"
# NOTE: Binance geo-blocks US IPs (HTTP 451) — pick a non-US zone.
ZONE="${ZONE:-europe-west1-b}"
NAME="${NAME:-factory-dryrun}"
MACHINE="${MACHINE:-e2-small}"

gcloud compute instances create "$NAME" \
  --project="$PROJECT" --zone="$ZONE" \
  --machine-type="$MACHINE" \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=20GB \
  --metadata=startup-script='#!/bin/bash
    # docker-compose-v2 does not exist on Debian 12; install the plugin binary
    apt-get update && apt-get install -y docker.io curl
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -sSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    systemctl enable --now docker'

echo "waiting for boot..."; sleep 45

# ship the deploy stack + observer (never .env — create it on the box)
tar czf /tmp/factory-deploy.tgz -C "$(dirname "$0")/../.." \
    deploy/docker-compose.yaml deploy/user_data/config.json \
    deploy/strategy deploy/.env.example factory/observer
gcloud compute scp /tmp/factory-deploy.tgz "$NAME":~ --project="$PROJECT" --zone="$ZONE"
gcloud compute ssh "$NAME" --project="$PROJECT" --zone="$ZONE" --command='
  echo "waiting for the startup script to finish installing docker...";
  for i in $(seq 1 60); do command -v docker >/dev/null && break; sleep 5; done;
  command -v docker >/dev/null || { echo "docker never appeared"; exit 1; };
  mkdir -p factory-deploy && tar xzf factory-deploy.tgz -C factory-deploy &&
  cd factory-deploy/deploy &&
  mkdir -p observer_data && sudo chown 1000:1000 observer_data &&
  cp .env.example .env &&
  sed -i "s/choose-a-long-password/$(openssl rand -hex 24)/" .env &&
  sed -i "s/choose-a-long-random-string/$(openssl rand -hex 32)/" .env &&
  sed -i "s/^DRYRUN_START=.*/DRYRUN_START=$(date -u +%Y%m%d)/" .env &&
  sudo docker compose up -d && sudo docker compose ps'

cat <<DONE

Up. Reach FreqUI through a tunnel:
  gcloud compute ssh $NAME --project=$PROJECT --zone=$ZONE -- -N -L 8080:localhost:8080
  open http://127.0.0.1:8080  (user freqtrader; password: cat ~/factory-deploy/deploy/.env on the box)
Watch:  gcloud compute ssh $NAME ... --command='tail -f factory-deploy/deploy/observer_data/snapshots.jsonl'
Parity: cat factory-deploy/deploy/observer_data/parity_report.md (daily)
Stop the meter: gcloud compute instances delete $NAME --project=$PROJECT --zone=$ZONE
DONE
