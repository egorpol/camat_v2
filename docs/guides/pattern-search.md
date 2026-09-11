---
title: Pattern search
---

# Pattern search

Use this part of [workflow 3](analysis.md) to locate a motif, chord progression,
or texture and inspect the matching passages in the score. You can extract a
query from existing music or define one independently. Statistical summaries
are a separate entry point; they are not a prerequisite for a search.

## Inputs and results

The search operates on a binary representation of `df_pitch` and a query with
compatible pitch and time axes. Keep matrix metadata, source-note provenance,
and the original MEI so matches can be highlighted in notation. See
[Binary representations](binary-representations.md) for constructing a matrix,
choosing its resolution, and understanding what the representation loses.

The tutorial notebooks build their own inputs from common-notation MEI. You
can start with a complete search task, then consult the methods notebooks as
needed.

## Choose a tutorial

Tutorial notebooks:

- [`binary_convolution_explained.ipynb`](../../notebooks/binary_convolution_explained.ipynb)
  — toy host/kernel placements and valid vs same padding on those windows,
  then sliding-window intuition, stride, and kernel scaling (time, pitch, or
  both) on Bach *Ein feste Burg*. Helpers: `convolution_map` /
  `score_kernel_at` in [pattern search](../api/pattern_search.md) and
  [binary convolution](../api/binary_convolution.md) plots;
- [`binary_pattern_search.ipynb`](../../notebooks/binary_pattern_search.ipynb)
  — a methods compendium: extract motif, chord, and texture kernels with their source coordinates;
  compare containment and correlation, merged and separate voices, and explicit
  augmentation recipes. Exclude the query's original passage, suppress nearby
  duplicate windows, then follow a ranked heatmap placement through the binary
  window and piano roll to highlighted notes in the complete original score.
- [`chord_progression_search.ipynb`](../../notebooks/chord_progression_search.ipynb)
  — one task from question to interpretation: define a D–A–D progression
  independently of the score, compare fixed MIDI, chroma and moving MIDI, choose time scales,
  search, inspect heatmaps, project every shortlisted hit to source notes and notation,
  and explain what the result does and does not establish. Start here for an
  applied workflow; use the compendium above as a methods reference.

## Define and run a query

Independent queries can use `camat.binary_query.search_binary_query`. MIDI
queries retain their specified voicing with explicit transpositions or a full
pitch/time scan via `transpositions="all"`. Chroma
queries retain all twelve classes and rotate circularly for key shifts, so
octave equivalence does not become an incorrect linear pitch-class placement.
Both representations retain source-cell provenance; chroma is never decoded
into an invented original voicing.

`convolution_map(...)` is the explicit overlap heatmap for one kernel.
`run_pattern_search(...)` is the full search entry point, with optional scale
factors and extra metrics. Kernels may be extracted from another matrix or
drawn interactively with `binary_matrix_designer(...)`.

```python
from camat import run_pattern_search

all_results, scaled_kernels, variant, last_result = run_pattern_search(
    matrix,
    kernel,
    metrics_to_run=["normalized_overlap"],
    padding="valid",  # or "same"
    backend="none",
)
```

## Interpret match scores

`normalized_overlap` measures containment: extra host notes are not penalized,
and 1.0 does not imply equal matrices. `normalized_cross_correlation` considers
both active and inactive cells (and returns 0 for constant windows/kernels).
`padding="valid"` (default) keeps the kernel inside the host;
`padding="same"` zero-pads the border so the score map can match the host
size at stride 1. Stride and kernel scale factors remain the knobs for window
motion and size.

## Augmentation and search settings

Meaningful comparison requires compatible pitch orientation and time
resolution. Pitch and time augmentation have independent policies:

- `kernel_pitch_mode="fixed"` keeps pitch rows unchanged, ignoring the pitch
  factor. `"intervals"` maps each row once to a scaled position, keeping each
  note one row thick and preserving chords. `"stretch"` enlarges rows as an
  image, so notes can become bands of adjacent pitches.
- `kernel_time_mode="events"` scales binary note-run boundaries before filling
  the new grid. `"resample"` samples the time cells using the selected method.
- `kernel_resize_method="nearest"` samples cell centres; `"bilinear"` retains
  legacy corner-aligned interpolation; `"area"` averages source-cell coverage.
  This method affects pitch only for `stretch` and time only for `resample`.
- `kernel_rounding="nearest"` (halves to even), `"floor"`, or `"ceil"` quantizes
  interval positions and event boundaries. Compression can merge pitches and
  can drop notes that quantize to zero duration. Collisions merge by maximum.

For musical motif experiments, the notebooks explicitly use:

```python
all_results, scaled_kernels, variant, last_result = run_pattern_search(
    matrix, kernel,
    metrics_to_run=["normalized_overlap"],
    kernel_scale_factors=[0.75, 1.0, 1.5, 2.0],
    kernel_scale_axes=["x", "y", "both"],
    kernel_pitch_mode="intervals",
    kernel_time_mode="events",
    kernel_rounding="nearest",
    backend="none",
)
```

On a semitone grid, six rows span five pitch intervals. Interval scaling at ×2
therefore gives eleven rows, with each source pitch mapped to one output row.
Row 0 is the anchor; scaling changes chromatic distances, not diatonic steps.
Combining `intervals` (or `fixed`) with `events` preserves input monophony.
Bilinear/area time sampling can blend consecutive notes into the same column,
even if pitch rows are individually preserved. A sustain-only binary grid cannot
recover voice identity or consecutive same-pitch articulations.

The library's compatibility defaults remain `stretch` + `resample` + `nearest`:
integer enlargement repeats every cell exactly, so `(6, 16)` at ×2 on both
axes becomes `(12, 32)`. `resize_kernel` accepts the corresponding shorter
keywords `pitch_mode`, `time_mode`, `method`, and `rounding`. It returns weights;
search can threshold them with `binarize_scaled_kernel` / `binarize_threshold`,
or keep fractional values. Geometric target sizes still use
`max(1, round(n * factor))`, independently of interval/event rounding.

Nondefault policies appear in search variant keys so results identify their
augmentation settings. `plot_kernel_augmentations` in
[binary convolution](../api/binary_convolution.md) compares named recipes on a
common cell scale and returns the plotted kernels. Enlarging a query does not
enlarge the host, so a low score on the original host does not imply a bad
augmentation. The explainer checks exact arrays and independently planted copies.

## Inspect the musical result

Follow a match from its heatmap position to the selected binary window and
source notes, then inspect those notes in the original score. A high numerical
score needs to be interpreted in relation to the chosen pitch axis, time
scales, voices, and similarity measure.

See [Return results to the score](analysis.md#return-results-to-the-score)
for the full connection, and
[Search by voice](binary-representations.md#search-by-voice-and-follow-a-match-back-to-notation)
for voice-specific matching and provenance examples.

## API documentation

- [Pattern search](../api/pattern_search.md): convolution maps, search settings,
  and metrics.
- [Independent binary queries](../api/binary_query.md): MIDI and chroma queries.
- [Binary convolution](../api/binary_convolution.md): explanatory plots.
