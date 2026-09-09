---
title: API reference
---

# API reference

Start with the [top-level API](api/camat.md) for common entry points available
through `import camat`. The pages below contain the full module documentation.

## Handle and inspect MEI

- [Edition and IIIF pipeline](api/edition_pipeline.md): facsimile integration and edition preparation.
- [MEI consistency and cleanup](api/mei_consistency.md): editorial validation and maintenance.
- [Facsimile viewer](api/facsimile_viewer.md): linked score and image inspection.
- [Verovio rendering](api/verovio_render.md): SVG scores, annotations, and highlights.

## Convert and parse

- [Conversion](api/conversion.md): individual files and mixed corpora.
- [MIDI timing](api/midi_timing.md): raw performance timing without notation quantization.
- [Parser registry](api/parser_registry.md) and [parser utilities](api/parser_utils.md): backend selection, source expansion, and summaries.
- [Verovio backend](api/verovio_backend.md): the default for common-notation MEI.
- [Partitura backend](api/partitura_backend.md): reference backend for parity tests.
- [Music21 backend](api/music21_backend.md) and [rendering](api/music21_render.md): compatibility helpers.

Convert non-MEI sources before using the default parser; see
[Convert to MEI](guides/formats.md).

## Analyse representations

- [Analysis utilities](api/analysis_utils.md): distributions, intervals, and piano rolls.
- [Binary matrix designer](api/binary_matrix_designer.md): pitch/time representations.
- [Binary convolution](api/binary_convolution.md): toy kernels and explainer plots.
- [Pattern search](api/pattern_search.md): kernels, placements, and similarity.
- [Overlays](api/overlay.md): connect matches to source notes.
- [Music utilities](api/music_utils.md): shared musical helpers.

## Experimental notation paths

- [Mensural utilities](api/mensural_utils.md).
- [Timeline backend](api/timeline_backend.md): rap-Humdrum parsing and `df_timeline`.

These paths have a different scope from common-notation MEI. Read the
[known limitations](known-limitations.md) before using them.
