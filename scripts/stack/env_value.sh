#!/usr/bin/env bash
# Print one variable's value from a KEY=VALUE env file, without sourcing it.
#   scripts/stack/env_value.sh NAME FILE
# Accepts `NAME=value`, `export NAME=value`, and a value in single or double
# quotes, which is how ~/.config/sophia/env is written. Sourcing the file would
# put the keyring variables beside it into the caller's environment, and the
# first version of this (a bare sed) handed the worker the quotes with the key,
# so every Gemini call it made was unauthorised.
set -euo pipefail
name="$1" file="$2"
[[ -r "$file" ]] || exit 0
value=$(sed -n "s/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}${name}=//p" "$file" | tail -1)
value="${value%"${value##*[![:space:]]}"}"
case "$value" in
    \"*\") value="${value#\"}"; value="${value%\"}" ;;
    \'*\') value="${value#\'}"; value="${value%\'}" ;;
esac
printf '%s' "$value"
