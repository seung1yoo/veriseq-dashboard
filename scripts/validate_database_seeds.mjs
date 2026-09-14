import { createHash } from "node:crypto";
import { access, readFile } from "node:fs/promises";
import { constants } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function countBy(values) {
  return values.reduce((counts, value) => {
    counts[value] = (counts[value] || 0) + 1;
    return counts;
  }, {});
}

function assertUnique(values, label) {
  assert(new Set(values).size === values.length, `${label} must be unique`);
}

async function exists(filePath) {
  try {
    await access(filePath, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

const catalogPath = path.join(repositoryRoot, "database", "seed", "nipt_catalog.v1.json");
const referencePath = path.join(repositoryRoot, "database", "seed", "dashboard_reference.v1.json");
const manifestPath = path.join(repositoryRoot, "database", "seed", "manifest.v1.json");

const [catalogBuffer, referenceBuffer, manifestBuffer] = await Promise.all([
  readFile(catalogPath),
  readFile(referencePath),
  readFile(manifestPath),
]);
const catalog = JSON.parse(catalogBuffer.toString("utf8"));
const reference = JSON.parse(referenceBuffer.toString("utf8"));
const manifest = JSON.parse(manifestBuffer.toString("utf8"));

assert(catalog.schema_version === 1, "Unsupported catalog seed schema");
assert(catalog.item_count === 258 && catalog.items.length === 258, "Catalog seed must contain 258 items");
assertUnique(catalog.items.map((item) => item.item_id), "item_id");
assertUnique(catalog.items.map((item) => item.glcp.marker_id), "marker_id");
assertUnique(catalog.items.map((item) => item.glcp.rs_id), "rs_id");
assertUnique(catalog.items.map((item) => item.output_order), "output_order");
assert(catalog.items.every((item, index) => item.output_order === index + 1), "Items must be stored in output_order");
assert(catalog.items.every((item) => item.active === true), "Initial catalog items must all be active");
assert(catalog.items.every((item) => item.glcp.normal_allele === "N" && item.glcp.risk_allele === "O"), "Unexpected allele mapping");
assert(catalog.items.every((item) => item.glcp.gene_id === item.display.item_name), "GLCP gene_id must use catalog item name");

const categoryCounts = countBy(catalog.items.map((item) => item.classification.category));
const consequenceCounts = countBy(catalog.items.map((item) => item.classification.consequence));
assert(categoryCounts.whole_chromosome_aneuploidy === 22, "Expected 22 whole-chromosome items");
assert(categoryCounts.sex_chromosome_aneuploidy === 4, "Expected 4 sex-chromosome items");
assert(categoryCounts.partial_cnv === 232, "Expected 232 CNV items");
assert(consequenceCounts.deletion === 162, "Expected 162 deletions");
assert(consequenceCounts.duplication === 70, "Expected 70 duplications");

const cnvItems = catalog.items.filter((item) => item.match_definition.method === "genomic_interval");
assert(cnvItems.length === 232, "Expected 232 interval items");
for (const item of cnvItems) {
  const regions = item.match_definition.regions;
  assert(item.match_definition.assembly === "GRCh37", `${item.item_id} assembly mismatch`);
  assert(item.match_definition.coordinate_system === "0-based-half-open", `${item.item_id} coordinate mismatch`);
  assert(Array.isArray(regions) && regions.length === 1, `${item.item_id} must have one region`);
  assert(Number.isInteger(regions[0].start) && Number.isInteger(regions[0].end), `${item.item_id} coordinates must be integers`);
  assert(regions[0].start >= 0 && regions[0].start < regions[0].end, `${item.item_id} interval is invalid`);
}

assert(reference.schema_version === 1, "Unsupported reference seed schema");
assert(reference.sample_classification_resolution_policy.source_sample_type_is_immutable === true, "Source sample_type must remain immutable");
assert(reference.sample_classification_resolution_policy.blocks_all_run_approvals === true, "Unclassified sample must block Run approval");
assert(reference.sample_classification_resolution_policy.requires_operator_reason === true, "Classification resolution must require a reason");
assert(reference.unknown_qc_flag_policy.blocks_all_run_approvals === true, "Unknown QC flag must block Run approval");
assert(reference.unknown_qc_flag_policy.manual_override_allowed === false, "Unknown QC flag must not allow manual override");
assert(reference.qc_parameters.length === 9, "Reference seed must define 9 QC parameters");
assert(reference.documented_boundary_status.metric_names.length === 6, "Reference seed must define 6 official boundaries");
assert(reference.initial_matching_settings.assembly === "GRCh37", "Matching assembly must be GRCh37");
assert(reference.initial_matching_settings.result_overlap_ratio.value === 0.5, "Result overlap ratio must start at 0.5");
assert(reference.initial_matching_settings.result_overlap_ratio.operator === ">", "Result overlap comparator must be strict");
assert(reference.initial_matching_settings.item_overlap_ratio.value === 0.5, "Item overlap ratio must start at 0.5");
assert(reference.initial_matching_settings.item_overlap_ratio.operator === ">", "Item overlap comparator must be strict");
assert(reference.glcp_export_profile.columns.join("\t") === "sample_id\tgene_id\trs_id\tallele_1_call\tallele_2_call", "GLCP columns mismatch");
assert(reference.glcp_export_profile.gene_id_field === "display.item_name", "GLCP gene_id authority mismatch");

for (const seedFile of manifest.seed_files) {
  const filePath = path.join(repositoryRoot, seedFile.file);
  const content = await readFile(filePath);
  assert(sha256(content) === seedFile.sha256, `${seedFile.file} checksum mismatch`);
}

const sourceChecks = [];
for (const sourceFile of manifest.source_files) {
  const filePath = path.join(repositoryRoot, sourceFile.file);
  if (!(await exists(filePath))) {
    sourceChecks.push({ file: sourceFile.file, status: "ABSENT_AS_ALLOWED" });
    continue;
  }
  const content = await readFile(filePath);
  assert(sha256(content) === sourceFile.sha256, `${sourceFile.file} checksum mismatch`);
  sourceChecks.push({ file: sourceFile.file, status: "MATCH" });
}

console.log(
  JSON.stringify({
    status: "PASS",
    catalog_items: catalog.items.length,
    qc_parameters: reference.qc_parameters.length,
    source_checks: sourceChecks,
  }),
);
