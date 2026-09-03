---
title: CAMAT Documentation
---
# CAMAT

CAMAT is an **MEI-centered toolbox for editorial and analytical work with
symbolic music**. You handle or import an MEI document, then move into Python
representations and analysis. The four workflows can be used independently.

```bash
pip install camat
```

Python 3.11 or later. Conceptual background is in
[What CAMAT is](overview.md). The full tutorial order is the
[notebook roadmap](notebooks.md).

## Choose a path

| If you already have… | Start with |
| --- | --- |
| MEI (a page, a combined score, or a draft edition) | **Workflow 1** — [Handling MEI files](guides/edition-building.md) |
| MusicXML, Humdrum, MIDI, MuseScore, or another symbolic format | **Workflow 2** — [Convert to MEI](guides/formats.md) |
| Checked MEI ready for tables | **Workflow 3** — [Parse and represent MEI](guides/parsing-representations.md) (placeholder) |
| Note tables or matrices | **Workflow 4** — [Analyse representations](guides/analysis.md) (placeholder) |

Workflows 1 and 2 have tutorial notebooks. Workflows 3 and 4 have guides
now; their showcase notebooks will grow as that work is written.

### Workflow 1 — handle MEI

Read [Introduction to MEI and XML](guides/mei-introduction.md), then work in
Jupyter. Open the notebooks from this checkout.

| Step | Notebook | Result |
| --- | --- | --- |
| Render | [`mei_render.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_render.ipynb) | paste or edit MEI and see the score |
| Inspect | [`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb) | score, with facsimile zones when they exist |
| Facsimile | [`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb) / [`mei_batch_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_batch_iiif_integration.ipynb) | IIIF graphic and measure zones |
| Combine | [`mei_combine_pages.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_combine_pages.ipynb) | page files joined into one `*_full.mei` |
| Check | [`mei_check_report.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_check_report.ipynb) | CSV editorial report |

The workflow hub is [Handling MEI files](guides/edition-building.md). Extra
flags live in
[`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb).

### Workflow 2 — convert to MEI

Conversion writes MEI for inspection and parsing. It does not produce a
reviewed edition. MIDI → music21 → Verovio is
[experimental](known-limitations.md).

| Step | Notebook | Result |
| --- | --- | --- |
| One score, learn routes | [`camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb) | MEI via Verovio, music21, or MuseScore |
| Many files, mixed corpus | [`camat_batch_conversion.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_batch_conversion.ipynb) | converted MEI plus a JSON report |

Guides: [Convert to MEI](guides/formats.md),
[Batch conversion](guides/batch-conversion.md),
[Test sources](guides/sources.md).

### Workflow 3 — parse and represent MEI

**Placeholder.** The guide
[Parse and represent MEI](guides/parsing-representations.md) describes
`df_pitch`, `df_events`, and the parser backends. The current notebook is
[`duration_semantics_examples.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/duration_semantics_examples.ipynb)
(segment vs logical vs performed duration). A general parse-to-tables tutorial
will be added here.

### Workflow 4 — analyse representations

**Placeholder.** The guide
[Analyse representations](guides/analysis.md) describes DataFrame summaries,
piano rolls, binary matrices, pattern search, and score overlays. There is no
end-to-end analysis notebook yet; that tutorial will be added here.

## Also in these docs

| Page | Use it for |
| --- | --- |
| [What CAMAT is](overview.md) | why MEI sits between edition, conversion, tables, and analysis |
| [Edition corpora](guides/edition-corpora.md) | DdT volumes in progress; where the editorial workflows came from |
| [Notebook roadmap](notebooks.md) | full numbered tutorial order |
| [Known limitations](known-limitations.md) | confirmed constraints, especially MIDI conversion |
| [Reference](reference.md) | Python API |

## Funding

CAMAT is funded by the German Research Foundation (DFG), programme
Library and Information Services — E-Research Technologies (LIS), grant
PF 669/18-1.
