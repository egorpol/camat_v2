---
title: Create MEI editions
---

# Create MEI editions

Edition-building is the first CAMAT workflow. The active production pipeline
and working corpus still live in the separate
[`camat_corpus`](https://github.com/egorpol/camat_corpus) repository, while the
reusable MEI/facsimile inspection viewer is now part of the `camat` Python
package. The two repositories are intended to be joined later.

## What this workflow does

The present `camat_corpus` workflow supports the creation and quality control
of MEI pages for the *Denkmäler deutscher Tonkunst* corpus. It includes:

- volume and source metadata;
- acquisition of page facsimiles through IIIF;
- measure detection and integration of facsimile zones into MEI;
- links from encoded measures to image regions;
- MEI consistency and page-coverage checks;
- interactive inspection of notation and facsimile alignment;
- progress and run-report notebooks.

These are **editorial and corpus-production tasks**. They differ from CAMAT's
conversion workflow, which imports one symbolic encoding into another without
making the result a reviewed edition.

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
| Editorial pipeline and corpus consistency notebooks | `camat_corpus` |
| Local MEI/facsimile link inspection | `camat_v2` / installed `camat` package |
| General file conversion to analysis MEI | `camat_v2` |
| MEI parsing and Python representations | `camat_v2` |
| DataFrame and matrix analysis | `camat_v2` |

Until the repositories are merged, install and run source acquisition, zone
generation, annotation integration, and corpus-wide validation from
`camat_corpus`. The facsimile viewer is the first workflow-one component that
has crossed that boundary because it reads any suitable local MEI and has no
DdT-specific pipeline dependency.

## Inspect a local MEI page

Use the
[`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb)
notebook or launch the viewer directly:

```python
from camat import launch_interactive_facsimile_viewer

viewer = launch_interactive_facsimile_viewer(
    "/path/to/page.mei",
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

Once an edition page has been inspected and is ready, continue with
[Parse and represent MEI](parsing-representations.md). If the source is not yet
MEI, use [File formats](formats.md) first and treat the converted file as an
import candidate requiring review.
