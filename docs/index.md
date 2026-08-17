---
title: CAMAT Documentation
---

# CAMAT

CAMAT is an **MEI-centered toolbox for editorial and analytical work with
symbolic music**. It supports a path from creating or importing an MEI document
through Python representations to analysis and score-linked results.

## Start with the workflow, not the module

| Goal | Guide |
| --- | --- |
| create and validate an MEI edition | [Create MEI editions](guides/edition-building.md) |
| import MusicXML, Humdrum, MIDI, MuseScore, or another format | [File formats](guides/formats.md) |
| turn MEI into Python tables and related representations | [Parse and represent MEI](guides/parsing-representations.md) |
| calculate distributions, binary matrices, or pattern matches | [Analyse representations](guides/analysis.md) |

The editorial production pipeline currently lives in the separate
`camat_corpus` repository. Its reusable local MEI/facsimile viewer, plus
conversion, parsing, analysis, and rendering, live here. Read [What CAMAT
is](overview.md) for the boundaries and the complete data flow.

## The central rule

MEI is the durable source document. DataFrames, piano rolls, binary matrices,
and match results are derived representations. Keep the MEI and the identifiers
that connect analytical results back to it.

For common music notation, `parse_files(...)` defaults to the Verovio backend
and accepts MEI. Convert non-MEI inputs first.

## Learn interactively

Follow the [notebook roadmap](notebooks.md) to choose the facsimile inspection,
single-file conversion, batch conversion, or representation example. The
roadmap also marks the parsing and analysis tutorials that still need to be
added.
