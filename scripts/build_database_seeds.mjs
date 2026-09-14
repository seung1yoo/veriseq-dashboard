import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const resourceDir = path.join(repositoryRoot, "resource");
const seedDir = path.join(repositoryRoot, "database", "seed");

const sourcePaths = {
  catalog: path.join(resourceDir, "nipt_item_catalog.json"),
  marker: path.join(resourceDir, "item_marker.tsv"),
  glcpExample: path.join(resourceDir, "glcp_standard_example.tsv"),
};

const expectedMarkerColumns = [
  "item_id",
  "marker_id",
  "item_name",
  "gene",
  "rs_id",
  "normal_allele",
  "risk_allele",
];
const expectedGlcpColumns = [
  "sample_id",
  "gene_id",
  "rs_id",
  "allele_1_call",
  "allele_2_call",
];

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function unique(values) {
  return new Set(values).size === values.length;
}

function parseTsv(content, { skipComments = false } = {}) {
  const lines = content.replaceAll("\r", "").trimEnd().split("\n");
  const comments = skipComments ? lines.filter((line) => line.startsWith("#")) : [];
  const tableLines = skipComments ? lines.filter((line) => !line.startsWith("#")) : lines;
  const columns = tableLines.shift().split("\t");
  const rows = tableLines.map((line, rowIndex) => {
    const values = line.split("\t");
    assert(values.length === columns.length, `TSV row ${rowIndex + 2} has invalid width`);
    return Object.fromEntries(columns.map((column, index) => [column, values[index]]));
  });
  return { comments, columns, rows };
}

function sameColumns(actual, expected) {
  return actual.length === expected.length && actual.every((value, index) => value === expected[index]);
}

const sourceBuffers = Object.fromEntries(
  await Promise.all(
    Object.entries(sourcePaths).map(async ([key, filePath]) => [key, await readFile(filePath)]),
  ),
);

const catalog = JSON.parse(sourceBuffers.catalog.toString("utf8"));
const markerTable = parseTsv(sourceBuffers.marker.toString("utf8"));
const glcpTable = parseTsv(sourceBuffers.glcpExample.toString("utf8"), { skipComments: true });

assert(catalog.item_count === 258, "Catalog item_count must be 258");
assert(catalog.items.length === 258, "Catalog items length must be 258");
assert(markerTable.rows.length === 258, "Marker row count must be 258");
assert(glcpTable.rows.length === 258, "GLCP example row count must be 258");
assert(sameColumns(markerTable.columns, expectedMarkerColumns), "Marker columns do not match the contract");
assert(sameColumns(glcpTable.columns, expectedGlcpColumns), "GLCP columns do not match the contract");

assert(unique(catalog.items.map((item) => item.item_id)), "Catalog item_id must be unique");
assert(unique(markerTable.rows.map((row) => row.item_id)), "Marker item_id must be unique");
assert(unique(markerTable.rows.map((row) => row.marker_id)), "marker_id must be unique");
assert(unique(markerTable.rows.map((row) => row.rs_id)), "rs_id must be unique");

const catalogById = new Map(catalog.items.map((item, index) => [item.item_id, { item, sourceOrder: index + 1 }]));
const markerByRs = new Map(markerTable.rows.map((row) => [row.rs_id, row]));
assert(markerTable.rows.every((row) => catalogById.has(row.item_id)), "Marker table has an unknown item_id");
assert(catalog.items.every((item) => markerTable.rows.some((row) => row.item_id === item.item_id)), "Catalog item is missing marker data");
assert(markerTable.rows.every((row) => row.normal_allele === "N" && row.risk_allele === "O"), "Unexpected allele code");

const categoryCounts = Object.groupBy
  ? Object.fromEntries(Object.entries(Object.groupBy(catalog.items, (item) => item.classification.category)).map(([key, values]) => [key, values.length]))
  : catalog.items.reduce((counts, item) => {
      counts[item.classification.category] = (counts[item.classification.category] || 0) + 1;
      return counts;
    }, {});
const consequenceCounts = catalog.items.reduce((counts, item) => {
  counts[item.classification.consequence] = (counts[item.classification.consequence] || 0) + 1;
  return counts;
}, {});
assert(categoryCounts.whole_chromosome_aneuploidy === 22, "Expected 22 whole-chromosome items");
assert(categoryCounts.sex_chromosome_aneuploidy === 4, "Expected 4 sex-chromosome items");
assert(categoryCounts.partial_cnv === 232, "Expected 232 CNV items");
assert(consequenceCounts.deletion === 162, "Expected 162 deletion items");
assert(consequenceCounts.duplication === 70, "Expected 70 duplication items");

for (const item of catalog.items.filter((entry) => entry.match_definition.method === "genomic_interval")) {
  const regions = item.match_definition.regions;
  assert(item.match_definition.assembly === "GRCh37", `${item.item_id} assembly must be GRCh37`);
  assert(item.match_definition.coordinate_system === "0-based-half-open", `${item.item_id} coordinate system mismatch`);
  assert(Array.isArray(regions) && regions.length === 1, `${item.item_id} must have exactly one region`);
  assert(Number.isInteger(regions[0].start) && Number.isInteger(regions[0].end), `${item.item_id} coordinates must be integers`);
  assert(regions[0].start >= 0 && regions[0].start < regions[0].end, `${item.item_id} interval is invalid`);
}

const glcpOrderMismatches = [];
const glcpCatalogNameMismatches = [];
const glcpMarkerGeneMismatches = [];
for (let index = 0; index < glcpTable.rows.length; index += 1) {
  const glcpRow = glcpTable.rows[index];
  const markerRow = markerTable.rows[index];
  assert(glcpRow.rs_id === markerRow.rs_id, `GLCP rs_id order differs at row ${index + 1}`);
  const catalogItem = catalogById.get(markerRow.item_id).item;
  if (glcpRow.gene_id !== catalogItem.display.item_name) {
    glcpCatalogNameMismatches.push({
      row: index + 1,
      item_id: markerRow.item_id,
      glcp_gene_id: glcpRow.gene_id,
      catalog_item_name: catalogItem.display.item_name,
    });
  }
  if (glcpRow.gene_id !== markerRow.gene) {
    glcpMarkerGeneMismatches.push({
      row: index + 1,
      item_id: markerRow.item_id,
      glcp_gene_id: glcpRow.gene_id,
      marker_gene: markerRow.gene,
    });
  }
  if (glcpRow.allele_1_call !== "N" || glcpRow.allele_2_call !== "N") {
    glcpOrderMismatches.push({ row: index + 1, reason: "example_call_is_not_normal" });
  }
}
assert(glcpOrderMismatches.length === 0, "GLCP normal example contains unexpected allele calls");

const markerCatalogNameMismatches = markerTable.rows
  .filter((row) => row.gene !== catalogById.get(row.item_id).item.display.item_name)
  .map((row) => ({
    item_id: row.item_id,
    marker_gene: row.gene,
    catalog_item_name: catalogById.get(row.item_id).item.display.item_name,
  }));

const seedItems = markerTable.rows.map((marker, index) => {
  const { item, sourceOrder } = catalogById.get(marker.item_id);
  return {
    ...item,
    active: true,
    output_order: index + 1,
    catalog_source_order: sourceOrder,
    glcp: {
      marker_id: marker.marker_id,
      rs_id: marker.rs_id,
      normal_allele: marker.normal_allele,
      risk_allele: marker.risk_allele,
      gene_id: item.display.item_name,
    },
    source_metadata: {
      item_marker_item_name: marker.item_name,
      item_marker_gene: marker.gene,
    },
  };
});

const catalogSeed = {
  schema_version: 1,
  seed_version: "public-1",
  catalog_version: catalog.catalog_version,
  item_count: seedItems.length,
  field_authority: {
    display_classification_and_match_definition: "nipt_item_catalog.json",
    marker_rs_and_alleles: "item_marker.tsv joined by item_id",
    output_order: "item_marker.tsv row order validated against glcp_standard_example.tsv rs_id order",
    glcp_gene_id: "catalog display.item_name",
  },
  defaults: {
    active: true,
  },
  source_provenance: catalog.sources,
  items: seedItems,
};

await mkdir(seedDir, { recursive: true });
const catalogSeedText = `${JSON.stringify(catalogSeed, null, 2)}\n`;
await writeFile(path.join(seedDir, "nipt_catalog.v1.json"), catalogSeedText, "utf8");

const referenceBuffer = await readFile(path.join(seedDir, "dashboard_reference.v1.json"));
const sourceManifest = [
  ["resource/nipt_item_catalog.json", "catalog", sourceBuffers.catalog],
  ["resource/item_marker.tsv", "marker_mapping_and_output_order", sourceBuffers.marker],
  ["resource/glcp_standard_example.tsv", "format_and_order_example", sourceBuffers.glcpExample],
].map(([file, role, content]) => ({ file, role, sha256: sha256(content) }));

const manifest = {
  schema_version: 1,
  manifest_version: "public-1",
  generated_on: "2026-09-02",
  source_files_are_disposable_after_implementation_validation: true,
  source_files: sourceManifest,
  validation_summary: {
    catalog_items: catalog.items.length,
    marker_rows: markerTable.rows.length,
    glcp_example_rows: glcpTable.rows.length,
    categorical_items: 26,
    cnv_items: 232,
    deletions: consequenceCounts.deletion,
    duplications: consequenceCounts.duplication,
    all_item_ids_joined: true,
    item_ids_unique: true,
    marker_ids_unique: true,
    rs_ids_unique: true,
    glcp_rs_order_matches_marker_order: true,
    glcp_example_all_normal_calls: true,
  },
  authority_decision: {
    catalog_is_authoritative_for_item_semantics: true,
    item_id_is_the_only_join_key: true,
    fuzzy_name_join_forbidden: true,
    output_order_source: "item_marker.tsv row order",
    glcp_gene_id_source: "catalog display.item_name",
  },
  known_source_differences: {
    marker_gene_vs_catalog_item_name: markerCatalogNameMismatches,
    glcp_gene_id_vs_catalog_item_name: glcpCatalogNameMismatches,
    glcp_gene_id_vs_marker_gene: glcpMarkerGeneMismatches,
    note: "Use catalog display.item_name as GLCP gene_id; do not infer semantic corrections.",
  },
  seed_files: [
    {
      file: "database/seed/nipt_catalog.v1.json",
      sha256: sha256(Buffer.from(catalogSeedText)),
    },
    {
      file: "database/seed/dashboard_reference.v1.json",
      sha256: sha256(referenceBuffer),
    },
  ],
};

await writeFile(path.join(seedDir, "manifest.v1.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(JSON.stringify(manifest.validation_summary));
