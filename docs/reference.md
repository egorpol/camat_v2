---
title: Reference
---

# Reference

## Backend Guidance

For common music notation, `verovio` is the default backend. CAMAT's analysis
workflow is MEI-first, and `parse_files(...)` resolves to `verovio` unless
`CAMAT_PARSER` or `parsing_backend` selects another backend.

- `verovio` parses common-notation MEI into the shared `df_pitch` and
  `df_events` result shape.
- `partitura` remains the ground-truth/reference backend for parity tests.
- `music21` remains available as a compatibility backend and conversion bridge.

The parser itself accepts common-notation MEI. Convert other formats first; see
[Convert to MEI](guides/formats.md). Verovio-supported formats convert directly;
unsupported music21-readable formats follow
`music21 -> MusicXML -> Verovio -> MEI`, so Verovio always produces the final
analysis file.

Mensural MEI and the `timeline` backend (MCFlow-style rap Humdrum, emitting
`df_timeline`) are experimental and have not been tested thoroughly; see
[Known limitations](known-limitations.md).

## Top-Level API

::: camat

## Module Reference

### Analysis utilities

::: camat.analysis_utils

### Binary matrix designer

::: camat.binary_matrix_designer

### Mensural utilities

::: camat.mensural_utils

### MEI facsimile viewer

::: camat.facsimile_viewer

### Music21 backend

::: camat.music21_backend

### Music21 render

::: camat.music21_render

### Music utilities

::: camat.music_utils

### Overlay

::: camat.overlay

### Parser registry

::: camat.parser_registry

### Parser utilities

::: camat.parser_utils

### Partitura backend

::: camat.partitura_backend

### Verovio backend

::: camat.verovio_backend

### Pattern search

::: camat.pattern_search

### Timeline backend

::: camat.timeline_backend

### Verovio render

::: camat.verovio_render
