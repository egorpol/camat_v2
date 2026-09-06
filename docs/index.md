---
title: CAMAT Documentation
---
# CAMAT

CAMAT is an **MEI-centered toolbox for editorial and analytical work with
symbolic music**. You handle or import an MEI document, then move into Python
representations and analysis. To start, install CAMAT with pip:

```bash
pip install camat
```

Use Python 3.11 or later.

Conceptual background is in [What CAMAT is](overview.md).

The full tutorial order is the [notebook roadmap](notebooks.md).

## Choose a path

| If you already have…                                          | Start with                                                                                        |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| MEI (a page, a combined score, or a draft edition)             | **Workflow 1** — [Handling MEI files](guides/edition-building.md)                           |
| MusicXML, Humdrum, MIDI, MuseScore, or another symbolic format | **Workflow 2** — [Convert to MEI](guides/formats.md)                                        |
| Checked MEI ready for parsing                                 | **Workflow 3** — [Parse and represent MEI](guides/parsing-representations.md) |
| Note tables or matrices                                        | **Workflow 4** — [Analyse representations](guides/analysis.md)                      |

Workflows 1–3 have tutorial notebooks. Workflow 4 covers DataFrame
statistics, binary round trips, and pattern search.

### Workflow 1 — handle MEI

Read [Introduction to MEI and XML](guides/mei-introduction.md), then work in
Jupyter. Open the notebooks from this checkout.

| Step      | Notebook                                                                                                                                                                                                                                                                      | Result                                      |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Render    | [`mei_render.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_render.ipynb)                                                                                                                                                                               | paste or edit MEI and see the score         |
| Inspect   | [`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb)                                                                                                                                                           | score, with facsimile zones when they exist |
| Facsimile | [`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb) / [`mei_batch_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_batch_iiif_integration.ipynb) | IIIF graphic and measure zones              |
| Combine   | [`mei_combine_pages.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_combine_pages.ipynb)                                                                                                                                                                 | page files joined into one`*_full.mei`    |
| Check     | [`mei_check_report.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_check_report.ipynb)                                                                                                                                                                   | CSV editorial report                        |

The workflow hub is [Handling MEI files](guides/edition-building.md). Extra
flags live in
[`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb).

### Workflow 2 — convert to MEI

Conversion writes MEI for inspection and parsing. It does not produce a
reviewed edition. MIDI → music21 → Verovio is
[experimental](known-limitations.md).

| Step                     | Notebook                                                                                                                | Result                                 |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| One score, learn routes  | [`camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb)                   | MEI via Verovio, music21, or MuseScore |
| Many files, mixed corpus | [`camat_batch_conversion.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_batch_conversion.ipynb) | converted MEI plus a JSON report       |

Guides: [Convert to MEI](guides/formats.md),
[Batch conversion](guides/batch-conversion.md),
[Test sources](guides/sources.md).

### Workflow 3 — parse and represent MEI

Parse checked common-notation MEI into Python tables, then annotate selections.
Mensural and timeline backends are [experimental](known-limitations.md).

| Step | Notebook | Result |
| --- | --- | --- |
| Parse to tables | [`mei_parse_tables.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_parse_tables.ipynb) | `df_pitch`, `df_events`, filtered piano roll |
| Annotate a selection | [`mei_annotate_selection.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_annotate_selection.ipynb) | `plist` / `tstamp` MEI annotations |
| Duration semantics | [`duration_semantics_examples.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/duration_semantics_examples.ipynb) | segment vs logical vs performed duration |

Guide: [Parse and represent MEI](guides/parsing-representations.md).

### Workflow 4 — analyse representations

Start from note tables (`df_pitch` / `df_events`) before matrices. Common-notation
MEI only; see [Known limitations](known-limitations.md).

| Step | Notebook | Result |
| --- | --- | --- |
| DataFrame statistics | [`df_statistics.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/df_statistics.ipynb) | pitch, duration, pitch-class, transition, interval, and onset distributions |
| Binary round trip | [`binary_roundtrip.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/binary_roundtrip.ipynb) | MEI → `df_pitch` / piano roll → binary → reconstruct → MEI highlight |
| Binary pattern search | [`binary_pattern_search.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/binary_pattern_search.ipynb) | motif, chord, and texture kernels with scaled-window search |

Guide: [Analyse representations](guides/analysis.md).

## Also in these docs

| Page                                        | Use it for                                                       |
| ------------------------------------------- | ---------------------------------------------------------------- |
| [What CAMAT is](overview.md)                 | why MEI sits between edition, conversion, tables, and analysis   |
| [Edition corpora](guides/edition-corpora.md) | DdT volumes in progress; where the editorial workflows came from |
| [Notebook roadmap](notebooks.md)             | full numbered tutorial order                                     |
| [Known limitations](known-limitations.md)    | CMN is the supported MEI schema; MIDI conversion and mensural/timeline paths are experimental |
| [Reference](reference.md)                    | Python API                                                       |

## Funding

CAMAT is funded by the German Research Foundation (DFG), programme
Library and Information Services — E-Research Technologies (LIS), grant
PF 669/18-1.
