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

Much of the current Workflow 1 tooling reflects the editorial path used for
*Denkmäler deutscher Tonkunst*, volume 11 (Buxtehude instrumental works): page
OMR from [musiconn.scoresearch](https://www.musiconn.de/services/musiconnscoresearch),
BSB IIIF facsimiles, assembly into work-level MEI, correction in
[mei-friend](https://mei-friend.mdw.ac.at/), and automated checks before
publication. See the edition README in
[`camat_corpus_editions` / `DdT_1_vol_11`](https://github.com/egorpol/camat_corpus_editions/tree/main/DdT_1_vol_11)
and its [editorial workflow notes](https://github.com/egorpol/camat_corpus_editions/blob/main/DdT_1_vol_11/docs/editorial-workflow.md)
for naming, status vocabulary, and the intended combine → check → correct loop.

In that production loop, combined or corrected MEI files were edited in
mei-friend, checked with the same passes exposed here, fixed from the report,
and re-checked until no encoded inconsistency remained. The tutorial notebooks
run those checks read-only; optional rewrite helpers stay in
[`mei_corrected_full_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/mei_corrected_full_checks.ipynb).

A complementary workflow—natural-language MEI editing in a code editor together
with [`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb)
for visual verification—is documented in
[`natural-language-mei-editing.md`](https://github.com/egorpol/camat_corpus/blob/main/natural-language-mei-editing.md)
in `camat_corpus`. It is experimental and will be featured more fully in a
later documentation pass.

## Choose a starting point

| If you want to…                                                                     | Start with                                                                                                                                  |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| understand MEI elements, attributes, schemas, and document structure                 | [Introduction to MEI and XML](mei-introduction.md)                                                                                           |
| paste or edit MEI and immediately render the score in Jupyter                        | [`mei_render.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_render.ipynb)                                             |
| inspect notation together with linked facsimile zones                                | [`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb)                         |
| add a IIIF facsimile and detected measure zones to one clean MEI file                | [`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb) |
| add IIIF facsimiles and measure zones to several MEI files                           | [`mei_batch_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_batch_iiif_integration.ipynb) |
| run automated editorial checks on one or more MEI files (read-only)                  | [`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb) with `COMBINE_PAGES = False` |
| join facsimile-linked page files into one score and check it                         | [`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb) with `COMBINE_PAGES = True` |
| check corrected full-score files with optional rewrite/cleanup flags                 | [`mei_corrected_full_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/mei_corrected_full_checks.ipynb)                         |
| build facsimile-linked MEI across a corpus                                           | [Add a facsimile and measure zones](#add-a-facsimile-and-measure-zones) below                                                                |

## Tutorial sequence

Follow this order when learning Workflow 1 end to end. Each step links to the next
guide or notebook; you can stop after any step if your file is not ready for the
rest.

1. **[Introduction to MEI and XML](mei-introduction.md)** — document structure,
   identifiers, written vs gestural attributes, and what the later checks look for.
2. **[`mei_render.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_render.ipynb)** —
   paste or edit MEI and render with Verovio while you work.
3. **[`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb)** —
   open an existing MEI (with or without facsimile data) and inspect layout and
   links read-only.
4. **IIIF integration** — add facsimile graphics and measure zones:
   [`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb)
   for one file, then
   [`mei_batch_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_batch_iiif_integration.ipynb)
   for many pages.
5. **Editorial checks** —
   [`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb):
   - **`COMBINE_PAGES = False`** — check a single page right after IIIF integration,
     several pages separately, or an already-combined full score;
   - **`COMBINE_PAGES = True`** — optional next step when several page files belong
     to one piece: prepare copies, join into `*_full.mei`, then run the same check
     suite on the combined file;
   - review **CSV/JSON reports** under `TARGET_DIR` (optional `<annot>` export is
     integrated but limited by mei-friend's annotation display cap).
6. **[`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb) again** —
   inspect the checked page or combined score against the facsimile; repeat
   edit → check → view until the report is acceptable.

Maintainer notebooks such as
[`mei_corrected_full_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/mei_corrected_full_checks.ipynb)
sit beside this sequence: same check passes, plus opt-in `CLEAN_*` / `FIX_*`
rewrites for production corpora.

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

| Concern                                                        | Repository                                 |
| -------------------------------------------------------------- | ------------------------------------------ |
| DdT working data, facsimiles, annotations, and metadata        | `camat_corpus`                           |
| Corpus inputs, working data, run configuration, and reports    | `camat_corpus`                           |
| Reusable IIIF, measure-zone, cleanup, and consistency pipeline | `camat_v2` / installed `camat` package |
| MEI/facsimile link inspection                                  | `camat_v2` / installed `camat` package |
| General file conversion to analysis MEI                        | `camat_v2`                               |
| MEI parsing and Python representations                         | `camat_v2`                               |
| DataFrame and matrix analysis                                  | `camat_v2`                               |

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

The batch notebook
[`mei_batch_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_batch_iiif_integration.ipynb)
runs the same job over a list of files (or a folder of already-named
`bsb…_NNNNN.mei` pages) through `plan_iiif_pages` and `integrate_iiif_pages`.
Its example is three clean Buxtehude pages in `test_corpus/`. Writes go to
`converted_mei/iiif_batch/` and stay off until `RUN_IIIF_INTEGRATION` is True.

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

## Check, combine, and review reports

The tutorial
[`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb)
runs CAMAT's read-only editorial suite on explicit MEI paths. It supports two
modes in one notebook:

| Mode | Flag | Typical input |
| --- | --- | --- |
| Check only | `COMBINE_PAGES = False` | one `*_facs_zones.mei` page after IIIF integration, several pages checked separately, or an existing `*_full.mei` / `*_corr.mei` |
| Combine then check | `COMBINE_PAGES = True` | several page files that belong to one piece (example: `test_corpus/buxtehude_pages/`) |

After the user enables `RUN_PIPELINE`, the notebook writes **CSV/JSON reports**
under `TARGET_DIR` (default `converted_mei/consistency_tutorial/`). In
**check-only** mode that is typically `input_consistency_report.csv` plus
`editorial_consistency_report.csv`. In **combine** mode it also writes prepared
copies under `unique_ids/` and `noppq/`, a joined `{stem}_full.mei`, a
`page_consistency_report.csv`, and `{stem}_full_consistency_report.csv`.
`MEI_INPUTS` may list local paths, directories, or `http(s)://` links (cached on
first use). Source files in `MEI_INPUTS` are not overwritten.

**Recommended workflow:** open the CSV/JSON reports under `TARGET_DIR`, filter
and track rows there (spreadsheet, pandas, or any text editor), correct the MEI
in mei-friend, inspect with the facsimile viewer, and re-run until the findings
you care about are resolved.

### `<annot>` export (integrated, CSV preferred)

CAMAT can also write selected findings into `<annot>` on a new
`*_annotated.mei` via `annotate_mei_from_report(...)` and
`ANNOTATE_COMBINED = True` in the notebook. That integration is useful for
small, filtered error sets you want to step through inside mei-friend.

In practice we rely on **CSV/JSON reports** because our correction loop runs
through [mei-friend](https://mei-friend.mdw.ac.at/), and mei-friend only
displays a limited number of annotations per score (`annotationDisplayLimit`,
default **100**, maximum **300** in
[settings](https://mei-friend.github.io/docs/basic/settings/)). A typical
combined-score report has far more rows than that. CSV/JSON is a practical
hand-off: easy to view, sort, filter, and edit while you fix the source MEI.

CAMAT mirrors mei-friend's scale with `MAX_ANNOTATIONS` (default 100) when
annotation export is enabled. The MEI schema itself does not cap `<annot>`
count ([`annot` element](https://music-encoding.org/guidelines/v5/elements/annot.html));
the limit is editor display, not encoding. For better support of large
machine-generated validation sets in mei-friend, see
[mei-friend/mei-friend issues](https://github.com/mei-friend/mei-friend/issues).

Optional rewrite/cleanup flags stay in the maintainer notebook below.

Checks include general consistency and publication-profile rules, figured-bass
`@startid` anchors, page-break facsimile links, the packaged MEI 5.1 CMN RELAX NG
schema, Verovio load/render warnings, and optional IIIF URL reachability.

The maintainer notebook
[`mei_corrected_full_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/mei_corrected_full_checks.ipynb)
checks already-combined score files and can rewrite them. Configure its `ROOT`
and `FULL_MEI_INPUTS`; its default flags are read-only. The passes cover:

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
