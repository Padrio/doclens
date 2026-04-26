#!/usr/bin/env bash
# doclens — run the document-indexing pipeline in Docker.
#
# Usage:
#   ./scripts/doclens.sh build               # build image (once)
#   ./scripts/doclens.sh convert [args]      # PDF → Markdown
#   ./scripts/doclens.sh describe [args]     # images → AI descriptions
#   ./scripts/doclens.sh index               # rebuild INDEX.md + TOC.md
#   ./scripts/doclens.sh report              # coverage stats
#   ./scripts/doclens.sh search "term" [slug]
#   ./scripts/doclens.sh shell               # interactive bash in container
#   ./scripts/doclens.sh all                 # convert + describe + index
#
# Mounts the calling directory (or DOCLENS_ROOT) into /work and runs
# scripts/*.py from there — so you can edit scripts/* without rebuilding.

set -euo pipefail

IMAGE_NAME="${DOCLENS_IMAGE:-ghcr.io/padrio/doclens:latest}"
KB_DIR="${DOCLENS_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

cmd="${1:-help}"
shift || true

cd "$KB_DIR"

ensure_image() {
    if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
        return 0
    fi
    echo "Image '$IMAGE_NAME' not found locally." >&2
    # Prefer pulling from registry when the tag looks like a remote one
    # (contains a slash or a registry host).
    if [[ "$IMAGE_NAME" == *"/"* ]]; then
        echo "Trying docker pull..." >&2
        if docker pull "$IMAGE_NAME" 2>&1 | tail -3 >&2; then
            return 0
        fi
        echo "Pull failed — falling back to local build (~5-15 min, one-time)..." >&2
    else
        echo "Building locally (~5-15 min, one-time)..." >&2
    fi
    docker build -t "$IMAGE_NAME" "$KB_DIR"
}

load_env_args() {
    if [[ -f .env ]]; then
        while IFS= read -r line; do
            case "$line" in
                ""|\#*) ;;
                *) printf -- "-e %q " "$line" ;;
            esac
        done <.env
    fi
}

docker_run() {
    ensure_image
    local env_args
    env_args=$(load_env_args)
    local tty_flag="-i"
    [[ -t 0 && -t 1 ]] && tty_flag="-it"
    # shellcheck disable=SC2086
    docker run --rm $tty_flag \
        -v "$KB_DIR":/work \
        -e "DOCLENS_ROOT=/work" \
        $env_args \
        "$IMAGE_NAME" "$@"
}

case "$cmd" in
    build)
        docker build -t "$IMAGE_NAME" "$KB_DIR"
        ;;
    convert)
        docker_run python scripts/convert.py "$@"
        ;;
    describe)
        docker_run python scripts/describe_images.py "$@"
        ;;
    index|build-index)
        docker_run python scripts/build_index.py "$@"
        ;;
    report)
        docker_run python scripts/describe_images.py --report
        ;;
    search)
        exec "$(dirname "$0")/search.sh" "$@"
        ;;
    sections)
        exec "$(dirname "$0")/search_sections.sh" "$@"
        ;;
    shell|bash)
        docker_run bash
        ;;
    all)
        docker_run python scripts/convert.py
        docker_run python scripts/describe_images.py
        docker_run python scripts/build_index.py
        ;;
    help|-h|--help|"")
        sed -n '1,17p' "$0"
        ;;
    *)
        echo "Unknown command: $cmd" >&2
        echo "Try '$0 help'." >&2
        exit 1
        ;;
esac
