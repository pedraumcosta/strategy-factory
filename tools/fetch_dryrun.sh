#!/bin/bash
# Fetch the deploy box's observer data + dry-run DB for a local review.
# Usage: PROJECT=... ZONE=... bash tools/fetch_dryrun.sh [dest-dir]
set -euo pipefail
PROJECT="${PROJECT:?}"; ZONE="${ZONE:?}"; NAME="${NAME:-factory-dryrun}"
DEST="${1:-runs/dryrun-review-$(date +%Y%m%d)}"
mkdir -p "$DEST"
gcloud compute ssh "$NAME" --project="$PROJECT" --zone="$ZONE" --command='
  cd factory-deploy/deploy &&
  sudo cp user_data/dryrun.sqlite /tmp/dryrun.sqlite 2>/dev/null &&
  sudo chown $(whoami) /tmp/dryrun.sqlite || true'
gcloud compute scp --project="$PROJECT" --zone="$ZONE" \
  "$NAME":factory-deploy/deploy/observer_data/snapshots.jsonl \
  "$NAME":/tmp/dryrun.sqlite "$DEST/" 2>/dev/null || true
gcloud compute scp --project="$PROJECT" --zone="$ZONE" \
  "$NAME":factory-deploy/deploy/observer_data/parity_report.md "$DEST/" 2>/dev/null || true
echo "fetched into $DEST:"
ls -la "$DEST"
echo "next: uv run factory dryrun-review $DEST"
