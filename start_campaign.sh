#!/bin/bash
# start_campaign.sh — Launch both calling lanes + live log monitor
# Usage: bash start_campaign.sh [--limit N] [--dry-run]
#
# Creates a tmux session "campaign" with 3 windows:
#   1. paul    — Lane A: 602, openai.onyx, municipal accounts (paul.txt)
#   2. alex    — Lane B: 480, gcloud, cold list (cold_outreach.txt)
#   3. monitor — Live webhook + SF push output

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIMIT=""
DRY=""
INTERVAL=60

for arg in "$@"; do
  case $arg in
    --limit=*) LIMIT="--limit ${arg#*=}" ;;
    --limit)   shift; LIMIT="--limit $1" ;;
    --dry-run) DRY="--dry-run" ;;
    --interval=*) INTERVAL="${arg#*=}" ;;
  esac
done

SESSION="campaign"

# Kill existing session if running
tmux kill-session -t "$SESSION" 2>/dev/null || true
sleep 1

# Create session with first window: Paul (Lane A)
tmux new-session -d -s "$SESSION" -n "paul" \
  "cd '$SCRIPT_DIR' && python3 campaign_runner_v2.py campaigns/sfdc-accounts.csv \
    --from +16028985026 \
    --voice openai.onyx \
    --prompt prompts/paul.txt \
    --business-hours \
    --interval $INTERVAL \
    --resume \
    $LIMIT $DRY; echo 'Paul lane finished. Press any key...'; read"

# Window 2: Alex (Lane B)
tmux new-window -t "$SESSION" -n "alex" \
  "cd '$SCRIPT_DIR' && python3 campaign_runner_v2.py campaigns/sled-territory-832.csv \
    --from +14806024668 \
    --voice openai.nova \
    --prompt prompts/cold_outreach.txt \
    --business-hours \
    --interval $INTERVAL \
    --resume \
    $LIMIT $DRY; echo 'Alex lane finished. Press any key...'; read"

# Window 3: Live monitor (webhook logs + call summaries)
tmux new-window -t "$SESSION" -n "monitor" \
  "cd '$SCRIPT_DIR' && echo '=== Live Call Feed ===' && pm2 logs hooks-server --nocolor --lines 20"

# Focus the monitor window by default
tmux select-window -t "$SESSION:monitor"

echo ""
echo "✅ Campaign started — tmux session: $SESSION"
echo ""
echo "   Attach:        tmux attach -t $SESSION"
echo "   Paul (Lane A): tmux attach -t $SESSION && Ctrl+b 0"
echo "   Alex (Lane B): tmux attach -t $SESSION && Ctrl+b 1"
echo "   Monitor:       tmux attach -t $SESSION && Ctrl+b 2"
echo "   Stop all:      tmux kill-session -t $SESSION"
echo ""
