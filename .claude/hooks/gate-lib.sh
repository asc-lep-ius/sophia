# Shared helpers for the quality gate. Sourced, never executed directly.

repo_root() {
    git -C "${1:-$PWD}" rev-parse --show-toplevel 2>/dev/null
}

# A stable identifier for "the current state of the working tree".
# Two invocations match if and only if nothing that would end up in a
# commit has changed.
fingerprint() {
    local head porcelain diff
    head=$(git rev-parse HEAD 2>/dev/null || echo "no-head")
    porcelain=$(git status --porcelain=v1 2>/dev/null || true)
    diff=$(git diff HEAD 2>/dev/null || true)
    printf '%s\n%s\n%s' "$head" "$porcelain" "$diff" \
        | sha256sum | cut -d' ' -f1
}

# Per-project gate commands. Anything left empty is skipped.
load_gates() {
    LINT_CMD=""; TYPE_CMD=""; TEST_CMD=""
    FORMAT_CMD=""; LINT_FILE_CMD=""; FORMAT_EXTENSIONS=""
    if [[ -f ".claude/gates.sh" ]]; then
        # shellcheck disable=SC1091
        source ".claude/gates.sh"
    elif [[ -f "pyproject.toml" ]]; then
        command -v ruff    >/dev/null && LINT_CMD="ruff check ."
        command -v pyright >/dev/null && TYPE_CMD="pyright"
        grep -q pytest pyproject.toml 2>/dev/null \
            && command -v pytest >/dev/null && TEST_CMD="pytest -q --tb=short"
    fi
}

state_dir() {
    local root="$1"
    printf '%s/.claude/state' "$root"
}

# Marker recording that one exact tree fingerprint passed every configured
# gate. Lets the Stop hook skip a re-run when nothing has changed since.
gates_marker() {
    printf '%s/gates-%s.ok' "$1" "$2"
}

# Run every configured gate against the working tree.
# Returns 0 when all pass; on failure returns 1 with GATE_FAILURES populated.
run_all_gates() {
    load_gates
    GATE_FAILURES=""
    local label cmd out
    for label in lint types tests; do
        case "$label" in
            lint)  cmd="$LINT_CMD" ;;
            types) cmd="$TYPE_CMD" ;;
            tests) cmd="$TEST_CMD" ;;
        esac
        [[ -z "$cmd" ]] && continue
        if ! out=$(eval "$cmd" 2>&1); then
            GATE_FAILURES+="--- ${label} (${cmd}) ---"$'\n'
            GATE_FAILURES+="$(printf '%s' "$out" | tail -30)"$'\n\n'
        fi
    done
    [[ -z "$GATE_FAILURES" ]]
}

# Record a pass. Keyed to the fingerprint as it was *before* the gates ran:
# if a gate mutates the tree, the next fingerprint differs and the gates
# simply re-run. Conservative by design — a stale pass is never honoured.
record_gates_pass() {
    local state="$1" fp="$2"
    {
        echo "passed_at=$(date -Iseconds)"
        echo "lint=${LINT_CMD}"
        echo "types=${TYPE_CMD}"
        echo "tests=${TEST_CMD}"
    } > "$(gates_marker "$state" "$fp")"
}
