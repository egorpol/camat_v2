---
title: Notebook roadmap
---

# Notebook roadmap

Choose a learning track according to your source material and musical question.
The three workflows have independent starting points. If you already have an
MEI score, you can begin with parsing or analysis; edition preparation is only
needed when your source requires it.

## Set up once, then choose a track

See [Getting started](getting-started.md#run-the-showcase-notebooks) for local
Jupyter installation and [Cloud notebooks](cloud-notebooks.md) for Jupyter4NFDI
and Colab. [`cloud_setup.ipynb`](../notebooks/cloud_setup.ipynb) installs CAMAT
and copies the tutorial folders. Colab starts a separate runtime for each
notebook tab; run each notebook's setup cell in its own runtime.

- [Workflow 1: Editing music with the MEI data format](#workflow-1-editing-music-with-the-mei-data-format)
  — import, render, check, or prepare a score and its facsimiles.
- [Workflow 2: Parse music into CAMAT representations](#workflow-2-parse-music-into-camat-representations)
  — explore note and event tables, selections, and durations.
- [Workflow 3: Analyse music: statistics and pattern search](#workflow-3-analyse-music-statistics-and-pattern-search)
  — summarize musical features or find matching passages.

Run a chosen notebook from the top and check its input configuration. Some
examples use packaged files, while others need a corpus file or an explicitly
enabled download. The order within a track is guidance for learning; you do
not need to finish the other tracks first.

## Workflow 1 — Editing music with the MEI data format

Guide: [Editing music with the MEI data format](guides/edition-building.md).
Start with the activity your source needs.

### Import another format, if needed

Skip conversion when your source is already MEI. These notebooks are
alternatives:

- [Convert one score](../notebooks/camat_formats.ipynb) explains MEI pass-through,
  direct Humdrum/MusicXML conversion, and MIDI/MuseScore bridges.
- [Convert a mixed corpus](../notebooks/camat_batch_conversion.ipynb) produces
  MEI files, technical validation, and a JSON report for a set of sources.

Then render and inspect the imported MEI.

### Render, edit, and inspect MEI

Start with [Render MEI](../notebooks/mei_render.ipynb) to paste or edit MEI and
render it interactively with Verovio. Read the
[Introduction to MEI and XML](guides/mei-introduction.md) when you need help
with document structure and editorial concepts.

Use [Inspect scores and facsimiles](../notebooks/mei_facsimile_viewer.ipynb)
for read-only inspection of a score, with optional links to source-image
regions. [Create an editorial report](../notebooks/mei_check_report.ipynb)
runs checks and writes a CSV report; inspect the score again after corrections.

### Prepare an edition with facsimiles

Use this sequence when working from page files and source images:

1. [Link one page to IIIF](../notebooks/mei_single_file_iiif_integration.ipynb),
   or [Link a batch to IIIF](../notebooks/mei_batch_iiif_integration.ipynb),
   to add facsimile links and measure zones.
2. [Combine MEI pages](../notebooks/mei_combine_pages.ipynb) to join page files
   into one `*_full.mei` score when needed.
3. [Create an editorial report](../notebooks/mei_check_report.ipynb), correct
   the score, and return to
   [Inspect scores and facsimiles](../notebooks/mei_facsimile_viewer.ipynb).

[Combine and check MEI](../notebooks/mei_consistency_checks.ipynb) provides the
full toolkit with extra flags as an alternative to the focused combine/check
notebooks.

## Workflow 2 — Parse music into CAMAT representations

Guide: [Parse music into CAMAT representations](guides/parsing-representations.md).
Start with a common-notation MEI file; conversion and facsimile work are not
prerequisites when you already have one.

Start with [Parse MEI to tables](../notebooks/mei_parse_tables.ipynb) to create
`df_pitch` and `df_events`, then view a full or filtered piano roll.

Choose a follow-up according to what you need:

- [Annotate a note selection](../notebooks/mei_annotate_selection.ipynb) filters
  notes and writes `plist` / `tstamp` MEI annotations. It parses its own source
  and can also be run directly.
- [Understand note durations](../notebooks/duration_semantics_examples.ipynb)
  explains encoded segment, logical, and performed duration. Consult it when
  choosing the duration column for an analysis.

## Workflow 3 — Analyse music: statistics and pattern search

Guide: [Analyse music: statistics and pattern search](guides/analysis.md).
The analysis tutorials prepare their own inputs. Choose statistics or search
directly; completing the parsing track first is optional.

### Statistics

Start with [Explore DataFrame statistics](../notebooks/df_statistics.ipynb)
for pitch, duration, pitch-class, transition, interval, and onset distributions
from `df_pitch`. It parses its own MEI file and compares a whole score with a
filtered selection. Companion guide: [Statistics](guides/statistics.md).

### Pattern search

Start with [Search for a chord progression](../notebooks/chord_progression_search.ipynb)
for a complete search task: define a D–A–D query, compare MIDI and chroma
representations and time scales, then inspect results in heatmaps, piano
rolls, and the original notation. Companion guide:
[Pattern search](guides/pattern-search.md).

Consult these method tutorials when you need more detail:

- [Understand binary convolution](../notebooks/binary_convolution_explained.ipynb)
  explains sliding windows, scoring, padding, and scaling with toy grids and
  Bach examples.
- [Binary search methods](../notebooks/binary_pattern_search.ipynb) compares
  motif, chord, and texture queries, voices, augmentation, filtering, and
  projection back to source notes.
- [Round trip through a binary matrix](../notebooks/binary_roundtrip.ipynb)
  follows MEI → tables / piano roll → binary → reconstruction → MEI highlight.
  Use it to investigate resolution, information loss, and provenance, alongside
  [Binary representations](guides/binary-representations.md).

## Workflow 1 maintainer notebooks

The notebooks in [the development archive](../CAMAT_old/README.md) —
`mei_corrected_full_checks.ipynb`, `single_mei_iiif_integration.ipynb`, and
`run_pipeline_workflow.ipynb` — are maintainer probes. They test real production behaviour, including rewrite
flags, rather than teach a portable user workflow.

Implementation probes such as `testing_verovio_conversion.ipynb`,
`testing_annot_stats.ipynb`, and `testing_binary_representations.ipynb` are
likewise outside the tutorial sequence.
