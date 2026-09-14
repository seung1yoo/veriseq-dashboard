# Architecture and output contracts

A browser connects to the local Nginx gateway. `/api/` and `/auth/` route to
FastAPI; other requests route to the vinext/React frontend. PostgreSQL stores
source inventories, ingestion revisions, normalized results, matching candidates,
users, approvals, and audit events. A separate worker claims import jobs.

Ingestion follows discovery → completeness/MD5 checks → transactional revision
storage → matching → conservative automatic negative approval. Raw strings are
retained beside parsed numeric values. Failed imports must not replace the prior
active revision. Source files are read-only; identity is run + flowcell + sample.

## Approved-result exports

Both endpoints accept `run_id`, `flowcell_id`, and `sample_result_ids`:

- `POST /api/v1/exports/glcp`: existing two comment lines and five-column GLCP TSV.
- `POST /api/v1/exports/results?format=csv` or `format=tsv`: common result table.

Common columns: `sample_id`, `run`, `flowcell`, `catalog_version`, `item_id`,
`item_name`, `item_result`, `sample_decision`, `approval_revision`, `approved_by`,
`secondary_findings`. Each active catalog item produces one row per selected
sample. Item result is positive only for selected approved items. Secondary
findings are retained as JSON in common exports; the fixed GLCP format has no
secondary-finding column.

All formats share selection and approval validation. Only reportable actual
samples from the active run revision with NEGATIVE/POSITIVE approval and QC
PASS/WARNING are eligible. FAIL/retest decisions cannot be exported as normal
results. Catalog IDs absent from the active catalog block output. Checksums and
export audit records are stored. The existing export metadata table is retained
for compatibility; it records all result formats, not only GLCP.

`GET /api/v1/exports/monthly-qc` is a separate sample-level QC CSV and includes
actual samples regardless of final approval. Its optional year/month filter uses
run start date. It is not an approved diagnostic result export.
