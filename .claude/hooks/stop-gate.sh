#!/usr/bin/env bash
# Stop — the involuntary half of the gate.
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

# --- escape hatches -------------------------------------------------------
# Never let the gate wedge a session. Three blocks per session is the ceiling.
ATTEMPTS_FILE="${STATE}/attempts-${SESSION_ID}"
ATTEMPTS=$(cat "$ATTEMPTS_FILE" 2>/dev/null || echo 0)
[[ "$ATTEMPTS" =~ ^[0-9]+$ ]] || ATTEMPTS=0
if (( ATTEMPTS >= 3 )); then
    rm -f "$ATTEMPTS_FILE"
    echo "gate: attempt limit reached, allowing stop" >&2
    exit 0
fi
[[ "${SHIP_GATE:-on}" == "off" ]] && exit 0
[[ -f "${STATE}/skip-${SESSION_ID}" ]] && exit 0

block() {
    echo $(( ATTEMPTS + 1 )) > "$ATTEMPTS_FILE"
    printf '%s\n' "$1" >&2
    exit 2
}

pass() {
    rm -f "$ATTEMPTS_FILE"
    exit 0
}

# --- did this session change anything? ------------------------------------
BASE_FILE="${STATE}/base-${SESSION_ID}"
[[ -f "$BASE_FILE" ]] || pass          # no baseline — don't gate
BASE_FP=$(cat "$BASE_FILE")
CUR_FP=$(fingerprint)
[[ "$BASE_FP" == "$CUR_FP" ]] && pass  # read-only session

# --- gate 1: build health -------------------------------------------------
# Skipped when this exact tree has already passed, so the gates cost one run
# per change rather than one run per turn.
if [[ ! -f "$(gates_marker "$STATE" "$CUR_FP")" ]]; then
    if ! run_all_gates; then
        block "Quality gate failed — fix before finishing:

${GATE_FAILURES}"
    fi
    record_gates_pass "$STATE" "$CUR_FP"
fi

# --- gate 2: review required ----------------------------------------------
# /ship is user-invoked only (disable-model-invocation), so the model has no
# legal way to clear this gate itself. Ask once per tree, then get out of the
# way — blocking again only burns turns on an instruction that cannot be
# obeyed. Deliberately does not touch ATTEMPTS: that budget is for gate 1,
# whose failures the model can actually fix.
if [[ ! -f "${STATE}/reviewed-${CUR_FP}.ok" ]]; then
    NUDGE_FILE="${STATE}/nudged-${SESSION_ID}-${CUR_FP}"
    if [[ -f "$NUDGE_FILE" ]]; then
        echo "gate: review pending, already asked for this tree — allowing stop" >&2
        pass
    fi
    : > "$NUDGE_FILE"
    printf '%s\n' "Code changed in this session but has not been reviewed.

You cannot clear this gate yourself — /ship is user-invoked only. Do not run the
reviewer, mark-reviewed.sh, or the skip file on the user's behalf, and do not
reproduce the /ship workflow by other means.

End the turn by telling the user the work is unreviewed and that they should run
/ship (or /ship --quick if a review already ran and the tree has moved since).
This gate will not block again for this tree. To bypass it deliberately, the
user can: touch ${STATE}/skip-${SESSION_ID}" >&2
    exit 2
fi

pass
