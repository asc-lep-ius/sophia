#!/usr/bin/env bash
# SessionStart — record the pre-session baseline so the gate can tell a session
# that wrote code from one that only answered questions.
set -uo pipefail

INPUT=$(cat) || INPUT='{}'
command -v jq >/dev/null 2>&1 || exit 0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/gate-lib.sh"

SESSION_ID=$(jq -r '.session_id // "no-session"' <<<"$INPUT")
CWD=$(jq -r '.cwd // ""' <<<"$INPUT")

ROOT=$(repo_root "${CWD:-$PWD}") || exit 0
cd "$ROOT" || exit 0

STATE=$(state_dir "$ROOT")
mkdir -p "$STATE"
fingerprint > "${STATE}/base-${SESSION_ID}"

# Housekeeping: markers older than a week are dead weight.
find "$STATE" -type f -mtime +7 -delete 2>/dev/null || true
exit 0
