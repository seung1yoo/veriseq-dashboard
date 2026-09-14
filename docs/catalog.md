# Laboratory catalogs

The default catalog has 258 items. Other laboratories may supply any nonempty
catalog at initial installation; 258 is not a runtime requirement.

Copy `database/seed/` to a local directory and set `VERISEQ_HOST_SEED_PATH` in
`.env` before the first startup. Preserve `dashboard_reference.v1.json`. Edit
`nipt_catalog.v1.json`, give it a distinct `catalog_version` and `seed_version`,
and set `item_count` to the number of entries. Each item requires:

- Unique `item_id` and positive integer `output_order`.
- `display.item_name`, `classification.category`, and a boolean `active`.
- A `match_definition` using categorical `veriseq_tokens`, or genomic intervals
  in `GRCh37` with `coordinate_system: "0-based-half-open"` and valid `regions`
  containing `chromosome`, integer `start`, and exclusive `end`.
- `glcp.marker_id`, `glcp.rs_id`, `glcp.normal_allele: "N"`, and `glcp.risk_allele: "O"`.
  Export identifiers must be unique and belong to the laboratory's export contract.

Use the supplied JSON as a complete schema example. Disease information and
laboratory export IDs are separate concepts; `rs_id` is not necessarily a dbSNP ID.
The current GLCP adapter uses the catalog display name for `gene_id` and supports
N/N and N/O result encoding. Other output systems can use the common CSV/TSV.

Source catalog development uses `resource/nipt_item_catalog.json`,
`resource/item_marker.tsv`, and the synthetic GLCP example. The scripts
`build_database_seeds.mjs` and `validate_database_seeds.mjs` reproduce and check
the **bundled default** catalog, including its expected 258-item composition.
Custom runtime seeds are validated by the Python loader instead.

Reusing a version with changed items is rejected. Activating a new catalog after
samples have been ingested is also rejected: existing matching and approvals must
not silently change. Use a fresh installation for evaluation of a new catalog;
production re-evaluation/import UI is not implemented in this release.

See `DATA_SOURCES.md` for default catalog attribution and adaptation status.
Source QC boundaries and the automatic negative approval policy are not changed
by selecting a different catalog.
