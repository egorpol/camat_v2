# Test corpus

This directory contains both URL manifests and checked-in MEI fixtures.
See [Test sources](../docs/guides/sources.md) for the external encoding projects
and commands that consume the manifests.

The [frozen validation baseline](validation_baseline/README.md) selects a tiny
synthetic CMN score, pinned Hummel and Webern encodings from the existing links,
and an ignored local DdT integration snapshot. It records provenance, input
hashes and before/after results for the general-checking boundary refactor.

The [offline parser robustness set](parser_robustness/README.md) selects a pinned
Bach chorale, that existing Hummel encoding and `tests/fixtures/basic.mei` for
installed-wheel smoke tests and a small local robustness run. Its manifest
records source revisions, input hashes and expected note/measure counts.

## Local Buxtehude fixtures

The standalone Buxtehude MEI files and `buxtehude_pages/` are used by editorial
checks and page-combination examples. Their source edition, encoding authorship,
and redistribution terms still need to be recorded before public release.
The age of the musical composition alone does not establish the terms for
its digital encoding or associated material.

Record the source URL or edition reference, encoding author, reuse license or
permission, and any local modifications here when provenance is confirmed.
These files are excluded from the PyPI wheel and source distribution.

Tiny synthetic unit-test and packaged tutorial scores are located separately
in `tests/fixtures/` and `camat/examples/`.

## Buxtehude Suite (DdT vol. 11, appendix no. 1)

| Field | Value |
| --- | --- |
| Fixture | `Buxtehude-DdT11-app01-suite.mei` |
| Source repository | [egorpol/DdT_1_vol_11](https://github.com/egorpol/DdT_1_vol_11) (public, MIT) |
| Source path | `11_buxtehude_sonatas_final/buxtehude_app_01_suite_to_op1_04_corr.mei` |
| Source commit | `63bdb24379c8c8def62696b6be862868ebc9e5bb` |
| Source sha256 | `d3283392ea95b1e811382cf445392dcb81fd073bacc264a97316f98ece9234c7` |
| Fixture sha256 | `f06ed03e16e41898e0e3e68d9046cd8eed4f708e9036fecdf8635568ed0df752` |
| Licence | MIT; see [`LICENSES/DdT_1_vol_11-MIT.txt`](../LICENSES/DdT_1_vol_11-MIT.txt). Copyright (c) 2026 contributors to DdT_1_vol_11 |

What was removed: the whole `<facsimile>…</facsimile>` block and every
`facs` token that pointed to an `xml:id` inside it. Everything else is
byte-identical to the source (unnumbered `<mdiv>`, seven `<pb>`, eight
`<sb>`, measure numbering 1–89). Rebuild with:

```bash
python scripts/strip_facsimile.py \
  pdf-workflow-test/dryrun-tutorial/source/buxtehude_app_01_suite_to_op1_04_corr.mei \
  test_corpus/Buxtehude-DdT11-app01-suite.mei
```

Used by [`notebooks/mei_pdf_facsimile_integration.ipynb`](../notebooks/mei_pdf_facsimile_integration.ipynb).
Excluded from the PyPI wheel and source distribution like the other files
in this directory.
