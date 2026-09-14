# Data sources and attribution

The MIT license covers original project code and documentation. It does not
relicense third-party data, dependencies, fonts, or trademarks.

## Default syndrome catalog

The project owner confirms that a contributor manually curated the disease
names, genomic coordinates, and deletion/duplication categories from
[Orphanet](https://www.orpha.net/). The supplied catalog is an adaptation, not
an official Orphanet release, and is not endorsed by Orphanet or INSERM.

[Orphadata Science](https://sciences.orphadata.com/) distributes its listed
open datasets under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The exact source release and ORPHAcode-to-item mapping were not recorded during
the manual curation. The catalog publishes Orphanet attribution and the CC BY
4.0 reference while clearly identifying itself as a manually curated adaptation.
It is not MIT-licensed and is not an official Orphanet dataset.

Public preparation removed branding, removed legacy metadata and Korean display
aliases, normalized local item/marker identifiers, and regenerated the GLCP
example with an invented sample. Genomic matching definitions were preserved.
GLCP `rs_id` values are export identifiers and must not be assumed to be dbSNP IDs.

The catalog uses GRCh37, 0-based half-open intervals. It is configurable and is
not a claim that every listed syndrome is validated for a given assay.

## Synthetic data

`backend/src/veriseq_dashboard/demo.py` constructs invented reports from explicit
constants. It does not read or pseudonymize clinical data. `resource/glcp_standard_example.tsv`
is an invented normal-result export. These original examples are covered by MIT.

## Other material

VeriSeq is an Illumina product name. This independent project does not bundle
Illumina software or manuals and does not imply endorsement. Obtain the
VeriSeq NIPT Solution v2 Software Guide from the manufacturer's official support site.

The bundled Pretendard font retains its SIL Open Font License in
`frontend/public/fonts/pretendard/LICENSE.txt`. JavaScript/Python dependencies
retain their respective licenses; consult installed package notices and the lockfile.
