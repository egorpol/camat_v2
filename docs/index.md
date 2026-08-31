---
title: CAMAT Documentation
---

# CAMAT

CAMAT is an **MEI-centered toolbox for editorial and analytical work with
symbolic music**. It supports a path from creating or importing an MEI document
through Python representations to analysis and score-linked results.

## Workflow overview

| Goal | Guide |
| --- | --- |
| understand, render, validate, or enrich an MEI file | [Handling MEI files](guides/edition-building.md) |
| import MusicXML, Humdrum, MIDI, MuseScore, or another format | [File formats](guides/formats.md) |
| turn MEI into Python tables and related representations | [Parse and represent MEI](guides/parsing-representations.md) |
| calculate distributions, binary matrices, or pattern matches | [Analyse representations](guides/analysis.md) |

The editorial production pipeline and corpus data currently live in the
separate `camat_corpus` repository. Reusable IIIF/measure-zone production, MEI
validation, cleanup, and facsimile-inspection helpers, plus conversion, parsing,
analysis, and rendering, live here. Read [What CAMAT is](overview.md) for the
boundaries and the complete data flow.

## The central rule

MEI is the durable source document. DataFrames, piano rolls, binary matrices,
and match results are derived representations. Keep the MEI and the identifiers
that connect analytical results back to it.

For common music notation, `parse_files(...)` defaults to the Verovio backend
and accepts MEI. Convert non-MEI inputs first.

## Learn interactively

Follow the [notebook roadmap](notebooks.md) for the Workflow 1 sequence: MEI
introduction, paste-and-render, facsimile inspection, IIIF integration,
editorial checks (check-only or combine-then-check), then conversion or
representation examples.
