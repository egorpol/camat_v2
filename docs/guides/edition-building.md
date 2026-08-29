---
title: Handling MEI files
---

# Handling MEI files

Handling MEI files is the first CAMAT workflow. It covers the source document
itself: understanding MEI and XML, rendering MEI while editing, checking and
cleaning files, inspecting facsimile links, and creating or enriching scholarly
editions. Edition-building is therefore one part of this broader workflow.

The active production pipeline and working corpus still live in the separate
[`camat_corpus`](https://github.com/egorpol/camat_corpus) repository. Reusable
IIIF acquisition, measure detection/integration, page coverage, validation,
MEI cleanup/consistency, and facsimile-inspection helpers are now part of the
`camat` Python package. The two repositories are intended to be joined later.

## Choose a starting point

| If you want to… | Start with |
| --- | --- |
| understand MEI elements, attributes, schemas, and document structure | [Introduction to MEI and XML](mei-introduction.md) |
| paste or edit MEI and immediately render the score in Jupyter | [`mei_render.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_render.ipynb) |
| add a BSB IIIF facsimile and detected measure zones to one clean MEI file | [`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb) |
| run corpus-style consistency checks and combine page files | [`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb) |
| check corrected full-score files with schema, profile, page-link, and Verovio passes | [`mei_corrected_full_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/mei_corrected_full_checks.ipynb) |
| inspect notation together with linked facsimile zones | [`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb) |
| build facsimile-linked MEI across a corpus | [Add a facsimile and measure zones](#add-a-facsimile-and-measure-zones) below |

The introductory guide was migrated from the project's earlier HfM Weimar
wiki. The MkDocs copy is now the project version to maintain; the
[original page](https://analyse.hfm-weimar.de/doku.php?id=en:mei) remains
available during the wider documentation migration.

## Editorial production as part of this workflow

The present `camat_corpus` workflow supports the creation and quality control
of MEI pages for the *Denkmäler deutscher Tonkunst* corpus. It includes:

- volume and source metadata;
- acquisition of page facsimiles through IIIF;
- measure detection and integration of facsimile zones into MEI;
- links from encoded measures to image regions;
- MEI consistency and page-coverage checks;
- interactive inspection of notation and facsimile alignment;
- progress and run-report notebooks.

These are **editorial and corpus-production tasks** within the broader MEI-file
workflow. They differ from CAMAT's conversion workflow, which imports one
symbolic encoding into another without making the result a reviewed edition.

## Hand-off to this repository

The integration point is the MEI file:

```text
camat_corpus editorial work
    -> reviewed MEI with metadata, facsimiles, and stable identifiers
    -> CAMAT parsing
    -> DataFrames and derived representations
    -> analysis, pattern search, and score overlays
```

For reliable downstream work, an edition should preserve unique `xml:id`
values. Measure numbering, facsimile links, and source metadata remain in the
MEI even when an analysis only uses note rows.

## Current boundary

| Concern | Repository |
| --- | --- |
| DdT working data, facsimiles, annotations, and metadata | `camat_corpus` |
| Corpus inputs, working data, run configuration, and reports | `camat_corpus` |
| Reusable IIIF, measure-zone, cleanup, and consistency pipeline | `camat_v2` / installed `camat` package |
| MEI/facsimile link inspection | `camat_v2` / installed `camat` package |
| General file conversion to analysis MEI | `camat_v2` |
| MEI parsing and Python representations | `camat_v2` |
| DataFrame and matrix analysis | `camat_v2` |

Until the repositories are merged, keep corpus-specific paths, inputs, images,
annotations, and generated reports in `camat_corpus`. The installed package
operates on explicit score directories and MEI paths, so the implementation no
longer depends on a `scripts/` folder in that repository.

## Add a facsimile and measure zones

The focused
[`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb)
notebook is the first editorial Workflow 1 tutorial. Its example is the clean
`test_corpus/Buxtehude-Anhang-S._185_musicxml_verovio.mei` file in this
repository. A read-only preflight confirms that the source has 17 measures and
no existing facsimile data. “Clean” is scoped to this integration step; schema
and editorial consistency are checked later. Identify the source page with a
Digitale Sammlungen `ARCHIVE_URL`, a pasted `IIIF_IMAGE_URL`, or both. After
the user explicitly enables the production flag, the notebook:

1. copies the source to a working name in `converted_mei/iiif_tutorial/`
   without changing the original;
2. downloads the facsimile image (the pasted IIIF URL when set, otherwise the
   BSB URL derived from the archive page);
3. sends that picture to the Edirom measure-detector network and integrates
   the returned measure boxes;
4. verifies the local image against the IIIF URL that was fetched;
5. writes and checks `{stem}_facs_zones.mei` with that IIIF graphic target.

The root-level maintainer notebooks expose the same production work at broader
scales:

- [`run_pipeline_workflow.ipynb`](https://github.com/egorpol/camat_v2/blob/main/run_pipeline_workflow.ipynb)
  inventories a score directory, optionally checks BSB manifest coverage, runs
  selected batch steps, and summarizes run/validation reports.

The tutorial notebook uses an example in this repository and writes
generated files under `converted_mei/`. The maintainer notebooks have
cleared outputs and disable network calls and writes by default; configure
their score-directory paths before enabling `RUN_*` flags. The equivalent
batch command is:

```bash
camat-run-pipeline /path/to/score-directory --skip-pages 1-29
```

Its five stages download facsimiles, upload/detect and integrate local measure
zones, compare local images with IIIF, rewrite graphic targets to IIIF, and
validate the final MEI. Individual commands such as
`camat-facsimile-download`, `camat-integrate-annotations`, and
`camat-validate-iiif` are also installed. The detector upload and BSB checks
require network access; reuse existing annotation XML when a repeated upload is
not intended. See the [edition pipeline API](../api/edition_pipeline.md).

## Check, combine, and annotate MEI

The copied corpus notebook
[`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb)
prepares page-level files, runs the general consistency report, combines the
pages, checks the combined file, and can create anchored MEI annotations from
selected report rows. It imports the packaged `camat.mei_consistency_workflow`
helpers; a separate `scripts/` checkout is no longer required.

The more recent
[`mei_corrected_full_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/mei_corrected_full_checks.ipynb)
checks already-combined score files. Configure its `ROOT` and
`FULL_MEI_INPUTS`; its default flags are read-only. The passes cover:

- internal references, identifiers, meters, durations, terms, and optional
  publication-profile rules;
- the packaged MEI 5.1 CMN RELAX NG schema;
- page-break links to facsimile surfaces;
- figured-bass `@startid` anchors that can be represented as `@tstamp` and
  `@staff`;
- Verovio load/render warnings.

The core consistency check is also available without a notebook:

```python
from pathlib import Path
from camat import check_mei_files

mei_path = Path("/path/to/edited.mei")
findings = check_mei_files(
    [mei_path],
    root_dir=mei_path.parent,
    check_ppq=True,
    publication_profile=True,
)
```

For CSV/JSON reports use `run_checker(...)`, or run
`camat-check-mei /path/to/edited.mei --publication-profile`. Cleanup and repair
helpers are opt-in and rewrite the selected MEI files only when `apply=True` or
the corresponding notebook flag is enabled. The RELAX NG pass uses the
packaged schema and requires the `xmllint` executable. See the
[MEI consistency API](../api/mei_consistency.md) for the individual passes.

## Inspect an MEI page

Use the
[`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb)
notebook or launch the viewer directly:

```python
from camat import launch_interactive_facsimile_viewer

viewer = launch_interactive_facsimile_viewer(
    "/path/to/page.mei",  # or an HTTP(S) / GitHub link
    allow_missing_facsimile=True,
    auto_watch_mei=True,
)
```

The viewer always renders the score with Verovio. Without facsimile records it
uses a full-width score-only view; when records exist it validates measure
`@facs` references, overlays zones on the first surface, and links both panes.
It is read-only: corrections remain part of the editorial workflow and must be
saved to the source MEI. See the
[facsimile viewer API](../api/facsimile_viewer.md) for the exact input contract,
local-image handling, caching, and file-watch behavior.

## Next step

Once an MEI file has been rendered, checked, and prepared for downstream use,
continue with [Parse and represent MEI](parsing-representations.md). If the
source is not yet MEI, use [File formats](formats.md) first and treat the
converted file as an import candidate requiring review.
