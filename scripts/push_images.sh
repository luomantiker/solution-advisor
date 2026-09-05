#!/bin/bash
set -e

REGISTRY="jfrog.realthon.com/realthon-docker-registry"
VERSION="${1:-0.1.0}"

images=(
  "solution-advisor-api:latest|solution-advisor-api:${VERSION}"
  "solution-advisor-common-analyzer:latest|solution-advisor-common-analyzer:${VERSION}"
  "solution-advisor-web:latest|solution-advisor-web:${VERSION}"
  "postgres:16-alpine|postgres:16-alpine"
  "redis:7-alpine|redis:7-alpine"
  "minio/minio:RELEASE.2025-04-22T22-12-26Z|minio:RELEASE.2025-04-22T22-12-26Z"
)

for item in "${images[@]}"; do
  src="${item%%|*}"
  dst="${item##*|}"

  echo "Push: $src -> $REGISTRY/$dst"

  docker tag "$src" "$REGISTRY/$dst"
  docker push "$REGISTRY/$dst"
done

echo "All images pushed."
