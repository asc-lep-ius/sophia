#!/usr/bin/env bash
# PreToolUse(Skill) — /ship starts when the user types it, or when the Stop gate
# asked for it for this exact tree in this session. A model that judged the work
# done on its own has no request marker to show, and is denied here rather than
# discouraged in prose. A typed `/ship`, and the milestone runner's `-p '/ship …'`,
# are user turns that never reach this hook.
set -uo pipefail
INPUT=$(cat) || INPUT='{}'

deny() {
    local reason="$1

/ship starts when the user types it, or when the Stop gate asks for it for this
exact tree in this session. Do not retry it. If the work is done, end the turn:
on an issue branch the gate asks for /ship for the tree as it then stands, and
anywhere else the user runs /ship themselves."
    if command -v jq >/dev/null 2>&1; then
        jq -n --arg r "$reason" '{
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: $r
          }
        }'
    else
        # Fixed text, so no escaping is needed and the refusal survives a box
        # with no jq — the one case where failing open would hand the model
        # the very invocation this hook exists to refuse.
        printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"skill-guard: jq is missing, so no request marker can be checked. Ask the user to run /ship."}}'
    fi
    exit 0
}

# The name is normalised the way the Skill tool resolves it — trimmed, one
# leading slash dropped, trimmed again — and compared without case, because a
# name the guard reads differently from the tool is a way past it: ` ship` and
# `ship ` both run /ship.
if ! command -v jq >/dev/null 2>&1; then
    shopt -s nocasematch
    [[ "$INPUT" =~ \"skill\"[[:space:]]*:[[:space:]]*\"[[:space:]]*/?[[:space:]]*([^\"]*:)?ship[[:space:]]*\" ]] \
        && deny "jq is missing"
    exit 0
fi

SKILL=$(jq -r '
    def trim: gsub("^[\\s\\p{Z}\\x{FEFF}]+|[\\s\\p{Z}\\x{FEFF}]+$"; "");
    .tool_input.skill // "" | trim | ltrimstr("/") | trim | ascii_downcase' <<<"$INPUT")
[[ "$SKILL" == "ship" || "$SKILL" == *:ship ]] || exit 0

# The runner sends /ship as a prompt, which never reaches this hook, and its
# gate never asks. A milestone turn reaching for the tool is doing something the
# runner did not sequence.
[[ -n "${MILESTONE_RUN:-}" ]] && deny "A milestone run starts /ship as a prompt from the runner, never through the Skill tool."

SESSION_ID=$(jq -r '.session_id // ""' <<<"$INPUT")
CWD=$(jq -r '.cwd // ""' <<<"$INPUT")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=gate-lib.sh
source "${SCRIPT_DIR}/gate-lib.sh"

ROOT=$(repo_root "${CWD:-$PWD}") || deny "Not a git repository, so there is no tree for /ship to review."
cd "$ROOT" || deny "Cannot enter ${ROOT}."
[[ -n "$SESSION_ID" ]] || deny "The hook was given no session id, so no request can be matched to this session."

STATE=$(state_dir "$ROOT")
FP=$(fingerprint)
[[ -f "$(ship_request_marker "$STATE" "$SESSION_ID" "$FP")" ]] && exit 0

# Which of the three refusals this is, because the right next move differs: a
# stale request means the tree moved after the gate asked, another session's
# means the evidence is not this conversation's to spend.
if compgen -G "$(ship_request_marker "$STATE" "$SESSION_ID" '*')" >/dev/null; then
    deny "The Stop gate asked for /ship on an earlier tree in this session, and the tree has moved since — the request was for code that is no longer what would be reviewed."
fi
if compgen -G "$(ship_request_marker "$STATE" '*' "$FP")" >/dev/null; then
    deny "The request for this tree belongs to another session; a request is evidence only for the session the gate asked."
fi
deny "The Stop gate has not asked for /ship in this session."
