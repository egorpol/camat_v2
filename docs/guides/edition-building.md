---
title: Create MEI editions
---

# Create MEI editions

Edition-building is the first CAMAT workflow, but it is not yet shipped in the
`camat` Python package. The active tools and working corpus live in the separate
[`camat_corpus`](https://github.com/egorpol/camat_corpus) repository. The two
repositories are intended to be joined later.

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
| Editorial pipeline and consistency notebooks | `camat_corpus` |
| General file conversion to analysis MEI | `camat_v2` |
| MEI parsing and Python representations | `camat_v2` |
| DataFrame and matrix analysis | `camat_v2` |

Until the repositories are merged, install and run the editorial workflow from
`camat_corpus`; do not expect those scripts from `pip install camat`.

## Next step

Once an edition page is ready, continue with
[Parse and represent MEI](parsing-representations.md). If the source is not yet
MEI, use [File formats](formats.md) first and treat the converted file as an
import candidate requiring review.

