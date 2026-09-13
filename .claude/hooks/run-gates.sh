#!/usr/bin/env bash
# Run the project's quality gates and, on success, record the pass so the Stop
# hook does not run them again for the same tree.
#
# Called by /ship step 2. Safe to run by hand at any time.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/gate-lib.sh"

ROOT=$(repo_root "$PWD") || { echo "not a git repo — no gates to run"; exit 0; }
cd "$ROOT" || exit 1

STATE=$(state_dir "$ROOT")
mkdir -p "$STATE"
FP=$(fingerprint)

if run_all_gates; then
    record_gates_pass "$STATE" "$FP"
    echo "Gates passed for tree ${FP:0:12}:"
    [[ -n "$LINT_CMD" ]] && echo "  lint  ${LINT_CMD}"
    [[ -n "$TYPE_CMD" ]] && echo "  types ${TYPE_CMD}"
    [[ -n "$TEST_CMD" ]] && echo "  tests ${TEST_CMD}"
    [[ -z "$LINT_CMD$TYPE_CMD$TEST_CMD" ]] && echo "  (none configured in .claude/gates.sh)"
    echo "The Stop hook will not re-run them until the tree changes."
    exit 0
fi

printf 'Quality gates FAILED:\n\n%s\n' "$GATE_FAILURES"
exit 1
