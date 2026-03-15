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

### Pattern search

::: camat.pattern_search

### Verovio render

::: camat.verovio_render
