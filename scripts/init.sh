#!/usr/bin/env bash
# doclens init — drop the pipeline into an existing project.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Padrio/doclens/main/scripts/init.sh | bash -s -- <target-dir>
#
# Or local from a clone:
#   ./scripts/init.sh /path/to/my-project/docs-source
#
# What it does:
# - Creates <target-dir>/{Dockerfile,pyproject.toml,scripts/,.env.example,
#   .dockerignore,.python-version,CLAUDE.md,AGENTS.md}
# - Does NOT touch existing files unless --force is passed
# - Prints next-step instructions
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <target-dir> [--force]" >&2
    exit 1
fi

TARGET="$1"
FORCE="${2:-}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$TARGET/scripts"

copy_file() {
    local src="$1" dst="$2"
    if [[ -e "$dst" && "$FORCE" != "--force" ]]; then
        echo "  skip   $dst (exists; use --force to overwrite)"
        return
    fi
    cp "$src" "$dst"
    echo "  write  $dst"
}

echo "Initializing doclens in: $TARGET"
copy_file "$SRC/Dockerfile" "$TARGET/Dockerfile"
copy_file "$SRC/.dockerignore" "$TARGET/.dockerignore"
copy_file "$SRC/.python-version" "$TARGET/.python-version"
copy_file "$SRC/pyproject.toml" "$TARGET/pyproject.toml"
copy_file "$SRC/.env.example" "$TARGET/.env.example"
copy_file "$SRC/CLAUDE.md.template" "$TARGET/CLAUDE.md"
copy_file "$SRC/AGENTS.md.template" "$TARGET/AGENTS.md"

for f in convert.py describe_images.py build_index.py search.sh search_sections.sh doclens.sh; do
    copy_file "$SRC/scripts/$f" "$TARGET/scripts/$f"
done
chmod +x "$TARGET"/scripts/*.sh 2>/dev/null || true

cat <<EOF

Done. Next:

  cd "$TARGET"
  cp .env.example .env                           # add ANTHROPIC_API_KEY
  cp <YOUR-PDFS>.pdf .                           # drop your documents in
  ./scripts/doclens.sh build                     # build container (once)
  ./scripts/doclens.sh all                       # convert + describe + index

Read CLAUDE.md / AGENTS.md for navigation rules in AI sessions.

EOF
