---
title: Reference
---

# Reference

## Backend Guidance

For common music notation, `partitura` is the recommended primary backend.
Use it by default for new work.

- `partitura` has the most complete support for MEI parsing in CAMAT.
- It provides reliable `xml_id` extraction and explicit `df_events` output.
- It is the reference implementation for common-notation parsing behavior.

`music21` remains available as a legacy backend. It can still parse
common-notation files and exposes the same top-level result structure, but it
should be treated as a compatibility option rather than the preferred parser.

`verovio` is available as an experimental common-notation MEI backend via
`parse_files(..., parsing_backend="verovio")` or the `"vrv"` alias. It reuses
the CAMAT result shape (`df_pitch`, `df_events`, `measure_offsets`, and
`barline_events`) and is intended for Partitura parity testing, not as the
default parser yet. Non-MEI inputs raise a clear error in this first milestone.

For MCFlow-style rap Humdrum timelines, use the `timeline` backend. It emits
`df_timeline` rows with stable MEI ids and optional rhythm-analysis columns for
duration and onset-position distributions.

## Top-Level API

::: camat

## Module Reference

### Analysis utilities

::: camat.analysis_utils

### Binary matrix designer

::: camat.binary_matrix_designer

### Mensural utilities

::: camat.mensural_utils

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
