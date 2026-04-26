#!/usr/bin/env bash
# Usage: ./scripts/search_sections.sh "pattern" [slug]
# For each hit, show the nearest preceding header + 2 lines of context.

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 \"pattern\" [slug]" >&2
    exit 1
fi

PATTERN="$1"
SLUG="${2:-}"

KB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KB_DIR" || exit 2

if [[ -n "$SLUG" ]]; then
    TARGET="docs/${SLUG}"
    if [[ ! -d "$TARGET" ]]; then
        echo "ERROR: slug '$SLUG' does not exist under docs/" >&2
        exit 2
    fi
else
    TARGET="docs"
fi

exec python3 - "$PATTERN" "$TARGET" <<'PYEOF'
import re
import sys
from pathlib import Path

pattern, target_root = sys.argv[1], Path(sys.argv[2])
header_re = re.compile(r"^(#+)\s+(.+?)\s*$")
needle_re = re.compile(re.escape(pattern), re.IGNORECASE)

any_hit = False
for md in sorted(target_root.rglob("*.md")):
    try:
        lines = md.read_text(encoding="utf-8").splitlines()
    except OSError:
        continue
    headers, matches = [], []
    for i, line in enumerate(lines, start=1):
        m = header_re.match(line)
        if m:
            headers.append((i, m.group(2).strip()))
        if needle_re.search(line):
            matches.append(i)
    if not matches:
        continue
    any_hit = True
    for idx in matches:
        nearest = "(no header)"
        for hline, htext in headers:
            if hline <= idx:
                nearest = htext
            else:
                break
        ctx = " ".join(lines[max(0, idx - 2):min(len(lines), idx + 1)]).strip()
        if len(ctx) > 200:
            ctx = ctx[:200] + "..."
        print(f"{md}:{idx}  [{nearest}]")
        print(f"    {ctx}")

sys.exit(0 if any_hit else 1)
PYEOF
