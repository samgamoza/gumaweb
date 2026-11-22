#!/usr/bin/env bash
# Deploy/upgrade GumaWeb to the current kube context.
#   TAG=0.1.0 scripts/deploy.sh [values-file]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VALUES="${1:-$ROOT/kubernetes/helm/gumaweb/values-prod.yaml}"
TAG="${TAG:?set TAG to the image tag to deploy}"

kubectl apply -f "$ROOT/kubernetes/namespaces.yaml"
helm lint "$ROOT/kubernetes/helm/gumaweb" -f "$VALUES" --set image.tag="$TAG"
helm upgrade --install gumaweb "$ROOT/kubernetes/helm/gumaweb" \
  --namespace guma-core -f "$VALUES" --set image.tag="$TAG" --wait --timeout 10m
kubectl -n guma-core rollout status deploy/gumaweb-api
