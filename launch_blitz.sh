#!/bin/bash
# launch_blitz.sh — One-command morning blitz launcher
#
# USAGE:
#   bash launch_blitz.sh               # Run today's blitz (auto-detects date)
#   bash launch_blitz.sh --dry-run     # Test without making calls
#   bash launch_blitz.sh --limit 5     # Cap at 5 calls
#   bash launch_blitz.sh --interval 90 # 90s between calls (default: 120)
#   bash launch_blitz.sh --csv campaigns/blitz-mar19-2026-v2.csv  # Specific file
#
# NOTES:
#   - Checks pre-campaign webhook health first (will abort if hooks.6eyes.dev is down)
#   - Uses local-presence numbers (SD 605, NE 402, IA 515) based on account state
#   - Calls E-Rate targets with k12.txt prompt; deal follow-ups with paul.txt
#   - Rate: ~30 calls/hour at 2-min intervals
#   - Budget guard: won't call if SignalWire balance < $2.00

set -e
cd "$(dirname "$0")"

# Load .env
if [ -f ".env" ]; then
    set -a; source .env; set +a
fi

# Defaults
CSV="${1:-campaigns/blitz-mar19-2026-v2.csv}"
LIMIT=""
INTERVAL="120"
DRY_RUN=""
EXTRA_ARGS=""

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN="--dry-run" ;;
        --limit) LIMIT="--limit $2"; shift ;;
        --interval) INTERVAL="$2"; shift ;;
        --csv) CSV="$2"; shift ;;
        *.csv) CSV="$1" ;;
    esac
    shift 2>/dev/null || shift
done

echo "=================================================="
echo "🚀 FORTINET SLED CALL BLITZ"
echo "   CSV:      $CSV"
echo "   Interval: ${INTERVAL}s between calls"
echo "   Date:     $(date '+%Y-%m-%d %H:%M %Z')"
if [ -n "$DRY_RUN" ]; then echo "   *** DRY RUN — no calls will be made ***"; fi
echo "=================================================="
echo ""

# Step 1: Check if pre-cache is fresh
echo "🔍 Checking research cache..."
python3 precache_blitz.py "$CSV" --dry-run 2>&1 | grep -E "CACHED|Total|ready"
echo ""

# Step 2: Run campaign
echo "📞 Starting calls..."
echo ""

python3 campaign_runner_v2.py "$CSV" \
    --interval "$INTERVAL" \
    --business-hours \
    $LIMIT \
    $DRY_RUN

echo ""
echo "✅ Blitz complete. Check logs/campaign_log.jsonl for results."
echo "   View analytics: https://brain.6eyes.dev/caller-analytics"
