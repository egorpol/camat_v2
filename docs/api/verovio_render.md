---
title: Verovio render
---

# Verovio render

`vrv_render_source_context` highlights selected IDs on complete original score
pages, retaining surrounding notes, rests and signatures. Use it to interpret
a search result in context. `vrv_render_symbolic_selection` produces an
isolated selection with unselected events replaced by invisible spaces.

For multiple search hits, pass `highlight_colors={source_id: color, ...}` to
`vrv_render_source_context`. Colors apply to selected note shapes, with the
default `highlight_color` for unmapped IDs; shared beams keep their original
color in this mode. Resolve overlapping hit membership to one display color per
source ID (the chord study uses gray). All groups on one page share a CSS scope;
separate rendered outputs remain isolated even when they contain the same IDs.

::: camat.verovio_render
