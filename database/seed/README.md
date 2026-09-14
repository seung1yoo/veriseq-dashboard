# Database seeds

`nipt_catalog.v1.json` supplies the default catalog; `dashboard_reference.v1.json`
supplies source-QC reference definitions. `manifest.v1.json` records checksums of
the default inputs and generated files. Rebuild with
`node scripts/build_database_seeds.mjs` and verify with
`node scripts/validate_database_seeds.mjs` from the repository root.

Catalog item semantics come from the source catalog. Marker/export order comes
from the marker table joined by `item_id`. The GLCP example checks format and
order and does not override disease semantics. See `docs/catalog.md` for custom
laboratory seeds and `DATA_SOURCES.md` for provenance restrictions.
