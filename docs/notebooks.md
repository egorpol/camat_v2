---
title: Notebook roadmap
---

# Notebook roadmap

The notebooks are executable companions to the conceptual guides. Each should
answer one main question, declare its input and output, and avoid relying on
state created by another notebook. See [Getting started](getting-started.md#run-the-showcase-notebooks)
for Jupyter installation, kernel selection, and first-run downloads.

## Recommended order

Workflow 1 — **Handling MEI files** — tutorial sequence:

| Order | Notebook | Main result |
| --- | --- | --- |
| 1 | [Introduction to MEI and XML](guides/mei-introduction.md) | MEI/XML structure and editorial concepts |
| 2 | [Render MEI](../notebooks/mei_render.ipynb) | paste or edit MEI and render interactively with Verovio |
| 3 | [Inspect scores and facsimiles](../notebooks/mei_facsimile_viewer.ipynb) | read-only inspection of MEI with optional measure–facsimile linking |
| 4 | [Link one page to IIIF](../notebooks/mei_single_file_iiif_integration.ipynb) | IIIF facsimile + measure zones on one clean MEI |
| 5 | [Link a batch to IIIF](../notebooks/mei_batch_iiif_integration.ipynb) | same IIIF job over many page files |
| 6 | [Combine MEI pages](../notebooks/mei_combine_pages.ipynb) | join page MEI files into one `*_full.mei` |
| 7 | [Create an editorial report](../notebooks/mei_check_report.ipynb) | editorial checks and a CSV report |
| 8 | [Combine and check MEI](../notebooks/mei_consistency_checks.ipynb) | full toolkit: combine + check + extra flags |
| 9 | [Inspect scores and facsimiles](../notebooks/mei_facsimile_viewer.ipynb) again | inspect the checked or combined MEI |

Later workflows (convert, parse, analyse):

| Order | Notebook | Workflow | Main result |
| --- | --- | --- | --- |
| 10 | [Convert one score](../notebooks/camat_formats.ipynb) | convert to MEI | corpus-backed MEI pass-through, direct Humdrum/MusicXML conversion, and MIDI/MuseScore bridges |
| 11 | [Convert a mixed corpus](../notebooks/camat_batch_conversion.ipynb) | convert to MEI | mixed-route MEI files, technical validation, and a JSON report |
| 12 | [Parse MEI to tables](../notebooks/mei_parse_tables.ipynb) | parse and represent MEI | one CMN MEI file → `df_pitch` / `df_events` and a filtered piano roll |
| 13 | [Annotate a note selection](../notebooks/mei_annotate_selection.ipynb) | parse and represent MEI | filter notes and write `plist` / `tstamp` MEI annotations |
| 14 | [Understand note durations](../notebooks/duration_semantics_examples.ipynb) | parse and represent MEI | note tables that distinguish segment, logical, and performed duration |
| 15 | [Explore DataFrame statistics](../notebooks/df_statistics.ipynb) | analyse representations | pitch, duration, pitch-class, transition, interval, and onset distributions from `df_pitch` |
| 16 | [Round trip through a binary matrix](../notebooks/binary_roundtrip.ipynb) | analyse representations | MEI → tables / piano roll → binary → reconstruct → MEI highlight |
| 17 | [Understand binary convolution](../notebooks/binary_convolution_explained.ipynb) | analyse representations | toy host/kernel placements and valid vs same padding, then sliding-window convolution on Bach |
| 18 | [Binary search methods](../notebooks/binary_pattern_search.ipynb) | analyse representations | compendium: scoring arithmetic, query extraction, voices, augmentation, filtering and source projection |
| 19 | [Search for a chord progression](../notebooks/chord_progression_search.ipynb) | analyse representations | task-driven independent D–A–D query: fixed MIDI, chroma and moving MIDI; all top hits in heatmaps, filled piano rolls and source notation; near-hit reflection |

For a complete search task, start with the chord-progression tutorial and refer
back to the binary search methods notebook when comparing algorithms or controls.

The conversion notebooks are alternatives after their shared introduction:
use the first for one score or for learning routes, and the second for a mixed
corpus.

## Workflow 1 maintainer notebooks

The notebooks in [the development archive](../CAMAT_old/README.md) —
`mei_corrected_full_checks.ipynb`, `single_mei_iiif_integration.ipynb`, and
`run_pipeline_workflow.ipynb` — are maintainer probes. They test real production behaviour, including rewrite
flags, rather than teach a portable user workflow.

Implementation probes such as `testing_verovio_conversion.ipynb`,
`testing_annot_stats.ipynb`, and `testing_binary_representations.ipynb` are
likewise outside the tutorial sequence.
