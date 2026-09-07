---
title: CAMAT Documentation
---
# CAMAT

CAMAT is an **MEI-centred toolbox for editorial and analytical work with
symbolic music**. You handle or import an MEI document, then move into Python
representations and analysis. These docs follow the code in this checkout.
For the matching package and tutorial notebooks, run from the repository root:

```bash
python -m pip install -e .
```

Use Python 3.11 or later.

`python -m pip install camat` installs the latest published PyPI release,
which may not include this checkout's beta changes. See
[Documentation and package versions](releasing.md#documentation-and-package-versions)
for how the release and development docs are kept in step.

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
| Render    | [`mei_render.ipynb`](../notebooks/mei_render.ipynb)                                                                                                                                                                               | paste or edit MEI and see the score         |
| Inspect   | [`mei_facsimile_viewer.ipynb`](../notebooks/mei_facsimile_viewer.ipynb)                                                                                                                                                           | score, with facsimile zones when they exist |
| Facsimile | [`mei_single_file_iiif_integration.ipynb`](../notebooks/mei_single_file_iiif_integration.ipynb) / [`mei_batch_iiif_integration.ipynb`](../notebooks/mei_batch_iiif_integration.ipynb) | IIIF graphic and measure zones              |
| Combine   | [`mei_combine_pages.ipynb`](../notebooks/mei_combine_pages.ipynb)                                                                                                                                                                 | page files joined into one`*_full.mei`    |
| Check     | [`mei_check_report.ipynb`](../notebooks/mei_check_report.ipynb)                                                                                                                                                                   | CSV editorial report                        |

The workflow hub is [Handling MEI files](guides/edition-building.md). Extra
flags live in
[`mei_consistency_checks.ipynb`](../notebooks/mei_consistency_checks.ipynb).

### Workflow 2 — convert to MEI

Conversion writes MEI for inspection and parsing. It does not produce a
reviewed edition. MIDI → music21 → Verovio is
[experimental](known-limitations.md).

| Step                     | Notebook                                                                                                                | Result                                 |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| One score, learn routes  | [`camat_formats.ipynb`](../notebooks/camat_formats.ipynb)                   | MEI via Verovio, music21, or MuseScore |
| Many files, mixed corpus | [`camat_batch_conversion.ipynb`](../notebooks/camat_batch_conversion.ipynb) | converted MEI plus a JSON report       |

Guides: [Convert to MEI](guides/formats.md),
[Batch conversion](guides/batch-conversion.md),
[Test sources](guides/sources.md).

### Workflow 3 — parse and represent MEI

Parse checked common-notation MEI into Python tables, then annotate selections.
Mensural and timeline backends are [experimental](known-limitations.md).

| Step | Notebook | Result |
| --- | --- | --- |
| Parse to tables | [`mei_parse_tables.ipynb`](../notebooks/mei_parse_tables.ipynb) | `df_pitch`, `df_events`, filtered piano roll |
| Annotate a selection | [`mei_annotate_selection.ipynb`](../notebooks/mei_annotate_selection.ipynb) | `plist` / `tstamp` MEI annotations |
| Duration semantics | [`duration_semantics_examples.ipynb`](../notebooks/duration_semantics_examples.ipynb) | segment vs logical vs performed duration |

Guide: [Parse and represent MEI](guides/parsing-representations.md).

### Workflow 4 — analyse representations

Start from note tables (`df_pitch` / `df_events`) before matrices. Common-notation
MEI only; see [Known limitations](known-limitations.md).

| Step | Notebook | Result |
| --- | --- | --- |
| DataFrame statistics | [`df_statistics.ipynb`](../notebooks/df_statistics.ipynb) | pitch, duration, pitch-class, transition, interval, and onset distributions |
| Binary round trip | [`binary_roundtrip.ipynb`](../notebooks/binary_roundtrip.ipynb) | MEI → `df_pitch` / piano roll → binary → reconstruct → MEI highlight |
| Convolution explainer | [`binary_convolution_explained.ipynb`](../notebooks/binary_convolution_explained.ipynb) | toy host/kernel placements and valid vs same padding, then Bach sliding-window animation; stride and kernel-size demos |
| Binary pattern search | [`binary_pattern_search.ipynb`](../notebooks/binary_pattern_search.ipynb) | motif, chord, and texture kernels with scaled-window search |

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
