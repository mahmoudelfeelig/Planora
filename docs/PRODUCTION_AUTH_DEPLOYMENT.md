# Production Authentication And Deployment

## Authentication model

Planora now uses first-party email/password accounts with invite-code onboarding.

1. A university admin creates a Planora group.
2. The admin creates an invite code for that group and chooses the starting role, such as `student`, `ta`, `professor`, or `uni_admin`.
3. A user registers with email, password, display name, and the invite code.
4. Planora stores only an Argon2 password hash and a hash of the invite code.
5. Planora sends an email confirmation link.
6. After confirmation, the user can sign in.

Invite codes are admission keys only. Rotating or disabling a leaked invite code does not remove existing users or group memberships. It only changes whether future users can register with that code.

## Environment file

For the simple single-server setup, put all configuration in `deploy/.env`. This is easier than Docker secrets, but it means `deploy/.env` contains real secrets. Do not commit it, do not share it, and restrict access to the deployment machine.

Create the env file:

```powershell
copy deploy\.env.example deploy\.env
```

Generate two random values and paste them into `PLANORA_AUTH_SECRET` and `PLANORA_TOKEN_PEPPER`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set these values in `deploy/.env`:

```env
PLANORA_DB_PATH=/app/data/planora.sqlite3
PLANORA_AUTH_SECRET=<long-random-secret>
PLANORA_TOKEN_PEPPER=<different-long-random-secret>
PLANORA_AUTH_ISSUER=planora
PLANORA_AUTH_AUDIENCE=planora-web
PLANORA_SESSION_TTL_SECONDS=28800
PLANORA_MAX_REQUEST_BYTES=20971520
PLANORA_RATE_LIMIT_PER_MINUTE=120
PLANORA_REGISTRATION_ENABLED=1
PLANORA_EMAIL_VERIFICATION_REQUIRED=1
PLANORA_DOMAIN=scheduler.example.edu
PLANORA_TLS_EMAIL=infra@example.edu
PLANORA_SMTP_HOST=smtp.example.edu
PLANORA_SMTP_PORT=587
PLANORA_SMTP_USERNAME=planora@example.edu
PLANORA_SMTP_PASSWORD=<smtp-password-or-app-password>
PLANORA_SMTP_FROM=Planora <planora@example.edu>
PLANORA_SMTP_STARTTLS=1
PLANORA_RETENTION_DAYS=183
PLANORA_BACKUP_KEEP_DAYS=183
PLANORA_BACKUP_KEEP_COUNT=800
```

## Deployment

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml up -d --build
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml ps
```

The API is not published directly. Caddy terminates HTTPS, strips `/api`, and applies browser security headers. `/health` checks the process and `/ready` checks database readiness.

## First administrator

Create a one-use bootstrap invite from the deployment host:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml exec planora-api python scripts/bootstrap_invite.py --database /app/data/planora.sqlite3 --tenant default --group "Initial admins" --role uni_admin --max-uses 1
```

The script prints the invite code once. Register with that code in the UI, confirm the email, then promote that account to global admin if needed:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml exec planora-api python scripts/bootstrap_access.py --database /app/data/planora.sqlite3 --user "email:admin@example.edu" --tenant "default" --role admin
```

Then sign in as that user, create the real university groups, create invite codes, and rotate/disable the bootstrap invite.

## Backup and restore

The backup container creates an integrity-checked SQLite snapshot every six hours. The production default keeps snapshots for 183 days with a count cap of 800 files in `planora-backups`. Copy backups to separate encrypted storage according to institutional retention policy.

Test restoration before launch and quarterly afterward:

```powershell
docker compose -f deploy/docker-compose.prod.yml run --rm planora-backup python scripts/backup_planora.py --source /app/data/restore-test.sqlite3 --restore /backups/<backup-file>
```

## Launch controls

- Use long random invite codes and rotate any code that leaks.
- Use single-use or low-use-count invites for admin roles.
- Keep `PLANORA_EMAIL_VERIFICATION_REQUIRED=1` in production.
- Restrict access to the deployment host and secret files.
- Alert on repeated `401`, `403`, `429`, job failures, readiness failures, disk usage, and backup age.
- Complete privacy review, data-retention policy, incident-response procedure, and external security testing before handling real student/staff data.
