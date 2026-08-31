---
title: What CAMAT is
---

# What CAMAT is

CAMAT is an **MEI-centered toolbox for editorial and analytical work with
symbolic music**. It is not a single converter or parser. It connects several
workflows by using MEI as the durable musical document between them.

The workflows can be used independently. An existing MEI edition can go
straight to parsing, while a MusicXML or Humdrum source first passes through
conversion.

## Four workflows

| Workflow | Starts with | Produces | Current location |
| --- | --- | --- | --- |
| 1. Handling MEI files | existing or draft MEI, or source material for an edition | understood, rendered, checked, corrected, or enriched MEI | introductory documentation, rendering, reusable validation, IIIF/measure-zone production, and inspection in this package; production data in [`camat_corpus`](https://github.com/egorpol/camat_corpus) |
| 2. Convert to MEI | MusicXML, Humdrum, MIDI, MuseScore, and other symbolic formats | MEI suitable for inspection and parsing | `camat.conversion` in this package |
| 3. Parse and represent MEI | common-notation MEI | Python result records, note and event DataFrames, and visual previews | this package |
| 4. Analyse representations | DataFrames or derived matrices | distributions, piano rolls, binary matrices, pattern matches, and score overlays | this package |

```mermaid
flowchart LR
    A[Scans, OMR, metadata] -->|editorial workflow| M[MEI document]
    B[MusicXML, Humdrum, MIDI, MuseScore] -->|conversion| M
    M -->|parse| D[Note and event DataFrames]
    D --> S[Statistical summaries]
    D --> P[Piano-roll views]
    D --> X[Binary matrices]
    X --> R[Pattern search]
    R --> O[Overlays and score rendering]
    D -. xml:id .-> M
    O -. xml:id .-> M
```

MEI is the center of this diagram deliberately. DataFrames and matrices are
derived working representations; they do not replace the edition.

## What each layer is responsible for

### MEI handling and editorial layer

This layer covers the MEI file itself: learning its XML structure, rendering it,
checking it, and improving it. Edition building is one important use case, with
corpus metadata, facsimile links, measure zones, validation, and corrections.
Production data mostly lives in the separate `camat_corpus` repository.
Reusable IIIF acquisition, measure detection/integration, consistency, schema,
page-link, Verovio, and read-only MEI/facsimile inspection helpers are available
in this package; the hand-off to later CAMAT workflows remains a valid MEI file
with stable `xml:id` values where possible.

### Conversion layer

Conversion imports a score from another encoding. Verovio writes the final MEI;
Music21 or MuseScore may act as an earlier bridge for formats Verovio cannot
read directly. Conversion is not editorial validation: the generated MEI must
still be inspected, especially after MIDI or OMR-derived input.

### Representation layer

The default Verovio parser reads common-notation MEI and separates two kinds of
information:

- `df_pitch`: note rows with pitch, onset, duration, voice, and MEI identity;
- `df_events`: rests, barlines, directions, dynamics, text, spans, and other
  non-note events.

The result record also carries context such as measure offsets and the parser
backend. See [Parse and represent MEI](guides/parsing-representations.md).

### Analysis layer

DataFrame analyses retain musically meaningful columns and identities. Matrix
analyses discretize pitch and time for operations such as pattern search. A
binary matrix is therefore a second-order representation derived from
`df_pitch`; its resolution and provenance metadata are part of its meaning.

See [Analyse representations](guides/analysis.md).

## Boundaries that prevent confusion

- **MEI is the source document.** Preserve it alongside every derived result.
- **Conversion does not certify an edition.** It changes encoding and may be
  lossy.
- **Parsing does not normally edit MEI.** It creates Python representations for
  inspection and analysis.
- **A piano roll is a view; a binary matrix is analysis data.** They may look
  similar, but the matrix has an explicit time grid and may fold or crop pitch.
- **`xml:id` is the bridge back to the score.** Retain identifiers and matrix
  provenance when an analysis result must be highlighted in notation.
- **Specialized sources have specialized contracts.** The timeline backend for
  rap Humdrum creates `df_timeline`; it is not a common-notation `df_pitch`
  parser.

## Choose a starting point

| If you want to… | Start here |
| --- | --- |
| learn the basic XML and MEI structure | [Introduction to MEI and XML](guides/mei-introduction.md) |
| paste MEI and render it interactively | [`mei_render.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_render.ipynb) |
| add an IIIF facsimile and measure zones to one clean MEI | [`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb) |
| add IIIF facsimiles and measure zones to several MEI files | [`mei_batch_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_batch_iiif_integration.ipynb) |
| run editorial checks on MEI (optionally combine pages first) | [`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb) |
| validate, clean, inspect, or enrich MEI | [Handling MEI files](guides/edition-building.md) |
| inspect measure-to-facsimile links in a local MEI | [MEI facsimile viewer](api/facsimile_viewer.md) |
| import another score format | [File formats](guides/formats.md) |
| convert a corpus and keep a report | [Batch conversion](guides/batch-conversion.md) |
| inspect MEI as Python objects and tables | [Parse and represent MEI](guides/parsing-representations.md) |
| calculate distributions or search musical patterns | [Analyse representations](guides/analysis.md) |
| learn interactively | [Notebook roadmap](notebooks.md) |
