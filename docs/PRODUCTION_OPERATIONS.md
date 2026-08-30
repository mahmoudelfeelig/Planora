# Planora Production Operations

## Daily Health Checks

- `curl -fsS https://planora.elfeel.me/api/health`
- `curl -fsS https://planora.elfeel.me/api/ready`
- `docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml ps`
- `docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml logs --tail=200 planora-api`

`/health` checks the API process. `/ready` checks the SQLite-backed persistence path and returns database schema metadata.

## SQLite Data

The official production cutover intentionally starts with an empty database in
new controller-owned data and backup volumes. Legacy Planora volumes are not
attached, imported, renamed, or deleted. The generic volume names in the
source Compose file apply only to local or independent self-hosting; they are
not the production state identity.

Inside the containers, the SQLite database remains at
`/app/data/planora.sqlite3` and verified snapshots remain under `/backups`.

Useful commands:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml exec planora-api python - <<'PY'
from services.persistence_service import default_persistence_path, PersistenceStore
from pathlib import Path
print(default_persistence_path(Path('/app')))
print(PersistenceStore(default_persistence_path(Path('/app'))).schema_info())
PY
```

List users from the deployment host:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml exec planora-api python - <<'PY'
import sqlite3
from pathlib import Path
from services.persistence_service import default_persistence_path
path = default_persistence_path(Path('/app'))
conn = sqlite3.connect(path)
conn.row_factory = sqlite3.Row
for row in conn.execute("SELECT user_id, tenant_id, role, email, disabled FROM users ORDER BY tenant_id, user_id"):
    print(dict(row))
PY
```

## Backup And Restore

Create a manual backup before upgrades:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml exec planora-backup python scripts/backup_planora.py
```

Restore procedure:

1. Stop the API: `docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml stop planora-api`.
2. Copy the selected backup into the data volume path used by `PLANORA_DB_PATH`.
3. Start the API: `docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml up -d planora-api`.
4. Run `/api/ready` and sign in as an admin.

## Email Deliverability

For Brevo or another SMTP provider:

- Verify the sending domain.
- Add SPF, DKIM, and DMARC records in Cloudflare.
- Set `PLANORA_SMTP_HOST`, `PLANORA_SMTP_PORT`, `PLANORA_SMTP_USERNAME`, `PLANORA_SMTP_PASSWORD`, `PLANORA_EMAIL_FROM`, and `PLANORA_PUBLIC_BASE_URL` in `deploy/.env`.
- Use Admin -> Email Deliverability to send a test message.

## Access And Audit

- University admins manage their own tenant groups, invites, and role bindings.
- Global admins can see every tenant and export audit/analytics CSVs.
- Rotate invite codes immediately if a code leaks. Existing members remain in the group.

## Upgrade And Rollback

Production upgrades are published only by the repository's small OIDC caller
after a successful `main` CI run. The private deployment controller pulls the
tested digest, runs readiness gates, records a signed receipt, and owns runtime
rollback. Do not add repository SSH credentials or perform direct host-side
Git and Compose deployment from this repository.

## Observability

Every API response includes `X-Request-ID`. In production or when `PLANORA_STRUCTURED_LOGS=1`, API logs are emitted as JSON and include method, path, client, and request ID.

## Monitoring

Add external uptime checks for:

- `https://planora.elfeel.me/api/health`
- `https://planora.elfeel.me/api/ready`

Use an external monitor such as UptimeRobot, Better Stack, Healthchecks.io, or Hetzner monitoring. Alert on non-2xx responses for two consecutive checks. `/health` confirms the API process is reachable; `/ready` confirms SQLite persistence is writable.

On the Hetzner server, alert at:

- Disk usage >= 80% warning, >= 90% critical.
- RAM usage >= 85% for 10 minutes.
- Backup age > 8 hours.
- Repeated 429/401/403 spikes in API logs.

## Cookie Check

Production Compose sets `PLANORA_PRODUCTION=1`, so auth cookies are emitted with `Secure`, `HttpOnly` for the session cookie, and `SameSite=Lax`. Confirm after login by checking successful login response headers include `Set-Cookie` values containing `Secure`.

## Retention

Current policy: keep audit logs, analytics events, backups, and old projects for 183 days.

- `PLANORA_RETENTION_DAYS=183` controls database cleanup.
- `PLANORA_BACKUP_KEEP_DAYS=183` controls backup age cleanup.
- `PLANORA_BACKUP_KEEP_COUNT=800` keeps enough six-hour snapshots for roughly six months plus margin.

The `planora-retention` service runs daily. To preview cleanup:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml exec planora-retention \
  python scripts/retention_planora.py --database /app/data/planora.sqlite3 --keep-days 183 --dry-run
```
