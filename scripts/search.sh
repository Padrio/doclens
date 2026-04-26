#!/usr/bin/env bash
# Usage: ./scripts/search.sh "pattern" [slug]
# Search the Markdown corpus. Hits inside DOCLENS_DESC HTML comments
# (image descriptions) are included.
#
# Uses ripgrep if installed on host; falls back to grep -R.

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 \"pattern\" [slug]" >&2
    exit 1
fi

PATTERN="$1"
SLUG="${2:-}"

KB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KB_DIR" || exit 2

if [[ -n "$SLUG" ]]; then
    TARGET=("docs/${SLUG}")
    if [[ ! -d "${TARGET[0]}" ]]; then
        echo "ERROR: slug '$SLUG' does not exist under docs/" >&2
        exit 2
    fi
else
    TARGET=("docs" "INDEX.md")
fi

# Prefer real ripgrep binary; skip shell-functions like the Claude-Code wrapper.
RG=""
for candidate in /opt/homebrew/bin/rg /usr/local/bin/rg /usr/bin/rg; do
    if [[ -x "$candidate" ]]; then RG="$candidate"; break; fi
done
[[ -z "$RG" ]] && RG=$(type -P rg 2>/dev/null || true)

if [[ -n "$RG" ]]; then
    "$RG" --type md --context 3 --heading --line-number --color never -- "$PATTERN" "${TARGET[@]}"
    rc=$?
else
    grep -R --include='*.md' -n -E -B 1 -A 2 -- "$PATTERN" "${TARGET[@]}"
    rc=$?
fi

if [[ $rc -eq 1 ]]; then
    echo "(no matches)" >&2
    exit 1
fi
exit $rc
