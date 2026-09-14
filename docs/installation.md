# Installation and operations

Use the quick-start configuration helper in the README, or copy `.env.example`
to `.env` and set unique credentials, source path, and administrator email.
The helper generates hexadecimal database credentials so they are safe in the
connection URL. If setting a database password manually, use URL-safe hexadecimal
characters or correctly encode connection-string characters.

| Setting | Meaning |
| --- | --- |
| `COMPOSE_PROJECT_NAME` | Namespace for containers and the persistent database volume; use a distinct name per installation |
| `VERISEQ_HOST_SOURCE_PATH` | Existing report directory, mounted read-only; relative paths resolve from the Compose project |
| `VERISEQ_HOST_SEED_PATH` | Optional custom seed directory; defaults to `./database/seed` |
| `VERISEQ_WEB_PORT` | Browser port, default 3000 |
| `VERISEQ_BIND_ADDRESS` | Loopback by default; change only for intentional network access |
| `VERISEQ_ALLOWED_EMAIL_DOMAIN` | Empty allows any valid email for administrator-issued accounts; otherwise enforces one exact domain |
| `VERISEQ_TIMEZONE` | Time zone used for default monthly reporting; default UTC |
| `VERISEQ_DEMO_MODE` | Imports only the fixed synthetic run when true; requires its marker and an isolated demo database |
| `VERISEQ_PUBLIC_BASE_URL` | Public URL; set an HTTPS URL when terminating TLS for this installation |

## Startup and account administration

Compose starts PostgreSQL, applies migrations and seed initialization, starts
the API and worker, and serves the frontend through a same-origin gateway. The
first administrator must change the generated temporary password within 24 hours.
Administration allows issuing operator/admin accounts, resetting passwords,
unlocking users, disabling access, and revoking sessions. No self-registration
or outbound email service is required. Transfer temporary passwords through an
appropriate local channel; the dashboard shows them once.

Keep `.env` local. A fresh install needs a unique project name and database volume;
never enable demo mode against an operational database. The configuration helper
refuses to overwrite existing files. Existing local `.env` files from older
versions are not automatically migrated.

## Operational checks

```bash
docker compose ps
docker compose logs --tail 100 migrate api worker frontend web
```

The source folder must exist and be readable by the container user. Initialization
fails rather than silently creating a missing source directory. No source report
is modified. Only the web gateway publishes a host port. The frontend makes
same-origin requests, so client computers do not need an API URL compiled into
JavaScript.

## Backup and restart

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U veriseq_dashboard veriseq_dashboard > backups/dashboard.sql
docker compose down
docker compose up -d
```

Backups contain laboratory data and must remain outside Git. Test restoration
into a separate database before relying on a backup. Keep source reports and
catalog versions with your laboratory retention controls. Do not run database
repair or bulk approval commands without a separate review and backup.
