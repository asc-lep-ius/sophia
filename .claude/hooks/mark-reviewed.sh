#!/usr/bin/env bash
# Called by /ship as its LAST step, after review passed and after any final
# commits. The marker is keyed by tree fingerprint, not by session.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/gate-lib.sh"

ROOT=$(repo_root "$PWD") || { echo "not a git repo — nothing to mark"; exit 0; }
cd "$ROOT" || exit 1

STATE=$(state_dir "$ROOT")
mkdir -p "$STATE"
FP=$(fingerprint)
{
    echo "reviewed_at=$(date -Iseconds)"
    echo "head=$(git rev-parse HEAD 2>/dev/null || echo none)"
    echo "verdict=${1:-APPROVED}"
} > "${STATE}/reviewed-${FP}.ok"

echo "Review recorded for tree ${FP:0:12}. The Stop gate will pass."
