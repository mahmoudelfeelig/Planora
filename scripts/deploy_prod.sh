#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${PLANORA_APP_DIR:-/opt/planora}"
REMOTE="${PLANORA_DEPLOY_REMOTE:-origin}"
BRANCH="${PLANORA_DEPLOY_BRANCH:-main}"
ENV_FILE="${PLANORA_ENV_FILE:-deploy/.env}"
COMPOSE_FILE="${PLANORA_COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
HEALTH_URL="${PLANORA_HEALTH_URL:-https://planora.elfeel.me/api/ready}"
HEALTH_ATTEMPTS="${PLANORA_HEALTH_ATTEMPTS:-24}"
HEALTH_SLEEP_SECONDS="${PLANORA_HEALTH_SLEEP_SECONDS:-5}"

cd "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing environment file: $APP_DIR/$ENV_FILE" >&2
  exit 2
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "$APP_DIR is not a git checkout." >&2
  exit 2
fi

previous_sha="$(git rev-parse HEAD)"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

wait_for_ready() {
  local require_head="${1:-1}"
  local attempt
  for attempt in $(seq 1 "$HEALTH_ATTEMPTS"); do
    if curl -fsS "$HEALTH_URL" >/dev/null && { [[ "$require_head" != "1" ]] || curl -fsSI "$HEALTH_URL" >/dev/null; }; then
      return 0
    fi
    echo "Health check attempt $attempt/$HEALTH_ATTEMPTS failed; retrying in ${HEALTH_SLEEP_SECONDS}s..."
    sleep "$HEALTH_SLEEP_SECONDS"
  done
  return 1
}

rollback() {
  trap - ERR
  echo "Deployment health check failed. Rolling back to $previous_sha..." >&2
  git reset --hard "$previous_sha"
  compose config --quiet
  compose up -d --build --remove-orphans
  if ! wait_for_ready 0; then
    echo "Rollback health check also failed. Inspect container logs manually:" >&2
    compose ps >&2 || true
    compose logs --tail=120 planora-api >&2 || true
    exit 1
  fi
  echo "Rollback complete."
  exit 1
}

trap rollback ERR

echo "Deploying Planora from $REMOTE/$BRANCH in $APP_DIR..."
git fetch --prune "$REMOTE" "$BRANCH"
git checkout -f -B "$BRANCH" "$REMOTE/$BRANCH"
git reset --hard "$REMOTE/$BRANCH"

compose config --quiet
compose up -d --build --remove-orphans
wait_for_ready

trap - ERR
echo "Planora deployed successfully: $(git rev-parse --short HEAD)"
compose ps
