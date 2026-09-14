# VeriSeq Dashboard

Self-hosted VeriSeq report ingestion, QC exploration, syndrome matching, review,
and approved-result exports. Run it on your own computer or laboratory server
with Docker Compose. This repository does not provide a hosted service.

## Quick start: synthetic demo

Requirements: Docker Engine/Desktop with Compose v2 and Python 3.10+ for the
local configuration helper. The initial build downloads container images and
packages; subsequent use reads local reports.

```bash
python3 scripts/configure.py --demo
# Read VERISEQ_INITIAL_ADMIN_PASSWORD in the generated local .env file.
docker compose up --build -d
```

Open **http://localhost:3000**, sign in as `admin@example.com` with the generated
password, and change it at first login. The demo has three entirely invented
samples: an automatically approved negative, a positive finding awaiting review,
and a QC failure awaiting review. No real clinical data is included.

The helper refuses to overwrite `.env`. Use a fresh checkout for a separate
installation. Set `--port 3001` if port 3000 is occupied.

## Laboratory installation

```bash
python3 scripts/configure.py --source /absolute/path/to/veriseq-results --admin admin@lab.example
docker compose up --build -d
```

The source directory is mounted **read-only**. Choose **Runs → Scan source** to
find runs, then import a ready run. The worker validates report completeness and
MD5 checksums before storing a revision. Database data persists in a named Docker
volume. `docker compose down` keeps that volume; do not use `down -v` for a
laboratory installation unless you intend to delete its database.

The web gateway binds to loopback by default. API and database ports are not
published. For access from other computers, configure the bind address and your
laboratory's network/TLS controls. All browser API requests use the same origin.

## Workflow

1. Scan the configured source directory and import ready runs.
2. Review source QC, sample metrics, region findings, and syndrome candidates.
3. Review and approve reportable results, or record FAIL/retest decisions.
4. Export the same approved results as common CSV, common TSV, or GLCP TSV.
5. Explore QC distributions and export sample-level QC data for the selected period.

Automatic negative approval is enabled on ingestion with the existing conservative
policy: actual sample, no approval block, QC PASS, no QC reason, explicit negative
autosomal/sex-chromosome/anomaly fields, exactly one zero CNV event count, no
findings or previous approvals, and no abnormal region classification. It never
replaces a manual approval. Audit events record automatic and manual actions.

## Configuration and limits

- [Installation and operations](docs/installation.md)
- [Catalog format and customization](docs/catalog.md)
- [Architecture and export contract](docs/architecture.md)
- [Data sources and outstanding catalog provenance](DATA_SOURCES.md)

English is the default UI and documentation language. Raw source values retain
their original meaning. Laboratory-specific catalogs can be supplied at initial
installation; changing a catalog after ingestion is deliberately blocked until
an explicit re-evaluation migration is available. Run folders currently require
`YYYY-MM-DD_<suffix>` names and one or two flowcells. No cross-run retest linkage
or patient demographic storage is implemented.

Validate the workflow and catalog for your own laboratory before operational use.
This project does not establish clinical validity or replace the manufacturer's
software or laboratory review procedures. Default catalog redistribution remains
pending the provenance review described in `DATA_SOURCES.md`.

## Development

```bash
python3 -m pip install -e './backend[dev]'
PYTHONPATH=backend/src python3 -m pytest backend/tests
node scripts/validate_database_seeds.mjs
cd frontend
npm ci
npm run lint
npm run build
```

For separate local development servers, `npm run dev` proxies `/api` and `/auth`
to the backend at `127.0.0.1:8000`. Development header authentication is disabled
in the Compose configuration. Production data, credentials, local archives,
and generated build artifacts must stay outside Git.

Code: [MIT](LICENSE). Data and third-party notices: [DATA_SOURCES.md](DATA_SOURCES.md).
