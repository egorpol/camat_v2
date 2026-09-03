---
title: Notebook roadmap
---

# Notebook roadmap

The notebooks are executable companions to the conceptual guides. Each should
answer one main question, declare its input and output, and avoid relying on
state created by another notebook.

## Recommended order

Workflow 1 — **Handling MEI files** — tutorial sequence:

| Order | Notebook | Main result |
| --- | --- | --- |
| 1 | [Introduction to MEI and XML](guides/mei-introduction.md) | MEI/XML structure and editorial concepts |
| 2 | [`mei_render.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_render.ipynb) | paste or edit MEI and render interactively with Verovio |
| 3 | [`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb) | read-only inspection of MEI with optional measure–facsimile linking |
| 4 | [`mei_single_file_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_single_file_iiif_integration.ipynb) | IIIF facsimile + measure zones on one clean MEI |
| 5 | [`mei_batch_iiif_integration.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_batch_iiif_integration.ipynb) | same IIIF job over many page files |
| 6 | [`mei_combine_pages.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_combine_pages.ipynb) | join page MEI files into one `*_full.mei` |
| 7 | [`mei_check_report.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_check_report.ipynb) | editorial checks and a CSV report |
| 8 | [`mei_consistency_checks.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_consistency_checks.ipynb) | full toolkit: combine + check + extra flags |
| 9 | [`mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb) again | inspect the checked or combined MEI |

Later workflows (convert, parse, analyse):

| Order | Notebook | Workflow | Main result |
| --- | --- | --- | --- |
| 10 | [`camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb) | convert to MEI | corpus-backed MEI pass-through, direct Humdrum/MusicXML conversion, and MIDI/MuseScore bridges |
| 11 | [`camat_batch_conversion.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_batch_conversion.ipynb) | convert to MEI | mixed-route MEI files, technical validation, and a JSON report |
| 12 | [`duration_semantics_examples.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/duration_semantics_examples.ipynb) | parse and represent MEI | note tables that distinguish segment, logical, and performed duration |

The conversion notebooks are alternatives after their shared introduction:
use the first for one score or for learning routes, and the second for a mixed
corpus.

## Coverage and next tutorials

| CAMAT workflow | Current coverage | Next documentation task |
| --- | --- | --- |
| Handling MEI files | MEI/XML introduction, render, facsimile inspection, IIIF integration, page combine, editorial-check report, full combine/check toolkit, maintainer cleanup | document rewrite/cleanup in the maintainer notebook path |
| Convert to MEI | corpus-backed single-file and batch notebooks, configurable MIDI grids, raw timing and voice-slot-to-staff diagnostics, resumability, and MuseScore | add larger-corpus performance and cache benchmarks |
| Parse and represent MEI | duration semantics example only | add a general MEI-to-`df_pitch`/`df_events` notebook |
| Analyse representations | no focused showcase notebook yet | add DataFrame → piano roll → binary matrix → pattern match → score overlay |

## Notebook contract

A CAMAT showcase notebook should include:

1. its workflow number and a link to the companion guide;
2. a small offline input, with network or external-tool examples kept optional;
3. a short statement of what each representation means;
4. explicit names for the MEI source, `df_pitch`, `df_events`, matrix, and
   matrix metadata rather than a chain of ambiguous `df` variables;
5. a final “what was produced?” summary and the next notebook or guide;
6. a clean-kernel execution check before publication.

## Workflow 1 maintainer notebooks

The root-level
`mei_corrected_full_checks.ipynb`, the older root-level
`single_mei_iiif_integration.ipynb`, and `run_pipeline_workflow.ipynb` are
maintainer probes. They test real production behavior, including rewrite
flags, rather than teach a portable user workflow.

Implementation probes such as `testing_verovio_conversion.ipynb` are likewise
outside the tutorial sequence.
