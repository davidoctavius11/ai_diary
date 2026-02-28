#!/usr/bin/env bash
# weekly_photo_sync.sh
# --------------------
# Runs the full photo pipeline incrementally:
#   sync → dedup → extract metadata → analyze → rebuild memory index
#
# Scheduled weekly via launchd (see LaunchAgents/com.brian.diary.weekly.plist).
# Safe to run manually at any time:
#   bash scripts/weekly_photo_sync.sh

set -euo pipefail

AI_DIARY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$AI_DIARY_DIR/venv/bin/python"
LOG_DIR="$AI_DIARY_DIR/logs"
LOG_FILE="$LOG_DIR/weekly_sync_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"

# Load .env so scripts pick up API keys
set -o allexport
# shellcheck disable=SC1091
source "$AI_DIARY_DIR/.env" 2>/dev/null || true
set +o allexport

echo "========================================" | tee -a "$LOG_FILE"
echo "Weekly photo sync — $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

run_step() {
    local name="$1"; shift
    echo "" | tee -a "$LOG_FILE"
    echo "--- $name ---" | tee -a "$LOG_FILE"
    if "$PYTHON" "$@" 2>&1 | tee -a "$LOG_FILE"; then
        echo "✓ $name done" | tee -a "$LOG_FILE"
    else
        echo "✗ $name failed (exit $?)" | tee -a "$LOG_FILE"
        # Don't stop — later steps are independent enough to still be useful
    fi
}

cd "$AI_DIARY_DIR"

run_step "Sync photos from Mac Photos" \
    scripts/sync_photos.py

run_step "Remove burst duplicates (moved to data/photos/duplicates/, reversible)" \
    scripts/dedup_photos.py --apply

run_step "Extract face + location metadata" \
    scripts/extract_photo_metadata.py

run_step "Analyze new photos with GLM vision" \
    scripts/photo_analyzer.py

run_step "Rebuild memory index" \
    scripts/fusion_engine.py

echo "" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "Weekly sync complete — $(date)" | tee -a "$LOG_FILE"
echo "Log saved to: $LOG_FILE" | tee -a "$LOG_FILE"

# Keep only the 10 most recent log files
ls -t "$LOG_DIR"/weekly_sync_*.log 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
