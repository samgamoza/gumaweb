#!/usr/bin/env bash
# Build and optionally push container images.
#   REGISTRY=registry.guma.local TAG=0.1.0 API_URL=https://api.gumaweb.io scripts/build-images.sh --push
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY="${REGISTRY:-registry.guma.local}"
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo dev)}"
API_URL="${API_URL:-https://api.gumaweb.io}"

docker build -f "$ROOT/backend/Dockerfile" -t "$REGISTRY/gumaweb/api:$TAG" "$ROOT"
docker build --build-arg NEXT_PUBLIC_API_URL="$API_URL" -t "$REGISTRY/gumaweb/portal:$TAG" "$ROOT/frontend"

if [ "${1:-}" = "--push" ]; then
  docker push "$REGISTRY/gumaweb/api:$TAG"
  docker push "$REGISTRY/gumaweb/portal:$TAG"
fi
echo "built $REGISTRY/gumaweb/{api,portal}:$TAG"
