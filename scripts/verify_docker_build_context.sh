#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
audit_dir="$(mktemp -d)"
trap 'rm -rf "$audit_dir"' EXIT

context_dir="$audit_dir/context"
output_dir="$audit_dir/output"
mkdir -p \
  "$context_dir/deploy/secrets" \
  "$context_dir/nested/.ssh" \
  "$context_dir/output" \
  "$context_dir/reports" \
  "$output_dir"
cp "$repo_root/.dockerignore" "$context_dir/.dockerignore"

printf '%s\n' 'FROM scratch' 'COPY . /context' >"$context_dir/Dockerfile"
printf '%s\n' 'public' >"$context_dir/public.txt"
printf '%s\n' 'must-not-ship' >"$context_dir/.env"
printf '%s\n' 'must-not-ship' >"$context_dir/deploy/.env"
printf '%s\n' 'must-not-ship' >"$context_dir/nested/.env.production"
printf '%s\n' 'must-not-ship' >"$context_dir/nested/prod.env"
printf '%s\n' 'must-not-ship' >"$context_dir/deploy/secrets/auth-token"
printf '%s\n' 'must-not-ship' >"$context_dir/nested/private.key"
printf '%s\n' 'must-not-ship' >"$context_dir/nested/.ssh/id_ed25519"
printf '%s\n' 'must-not-ship' >"$context_dir/nested/id_rsa"
printf '%s\n' 'must-not-ship' >"$context_dir/output/local-result.json"
printf '%s\n' 'must-not-ship' >"$context_dir/reports/local-report.json"

docker buildx build \
  --progress=quiet \
  --output "type=local,dest=$output_dir" \
  "$context_dir" >/dev/null

test -f "$output_dir/context/public.txt"
for forbidden in \
  "$output_dir/context/.env" \
  "$output_dir/context/deploy/.env" \
  "$output_dir/context/nested/.env.production" \
  "$output_dir/context/nested/prod.env" \
  "$output_dir/context/deploy/secrets/auth-token" \
  "$output_dir/context/nested/private.key" \
  "$output_dir/context/nested/.ssh/id_ed25519" \
  "$output_dir/context/nested/id_rsa" \
  "$output_dir/context/output/local-result.json" \
  "$output_dir/context/reports/local-report.json"
do
  if [[ -e "$forbidden" ]]; then
    echo "Sensitive file entered the Docker build context: $forbidden" >&2
    exit 1
  fi
done

echo "Docker build context excludes secrets and generated institutional evidence."
