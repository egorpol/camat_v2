---
title: Analyse representations
---

# Analyse representations

This is **CAMAT workflow 4**. Start with DataFrame summaries on `df_pitch`, then
move to binary matrices and pattern search when you need a discrete pitch/time
grid.

CAMAT has two complementary analysis layers:

1. **DataFrame analysis**, which works with musical columns and MEI identities;
2. **matrix analysis**, which discretizes pitch and time for image-like pattern
   operations.

Start with the least transformed representation that answers the question.

## DataFrame analysis

Tutorial notebook:
[`df_statistics.ipynb`](../../notebooks/df_statistics.ipynb)
(CMN only). It parses one MEI file for itself and shows:

- pitch and pitch-class distributions;
- metric or logical duration distributions (see also
  [`duration_semantics_examples.ipynb`](../../notebooks/duration_semantics_examples.ipynb));
- a monophony check before sequential analyses;
- successive-pitch transition heatmaps and melodic intervals;
- onset positions within measures (uses `df_events` / parse `results`).

Optional comparison stays simple: one full score plus one filtered selection.

For example:

```python
from camat import build_duration_counts, build_pitch_counts

pitch_counts, pitch_axis = build_pitch_counts(df_pitch, axis_option="pitch")
duration_counts, duration_axis = build_duration_counts(
    df_pitch,
    duration_column="Duration",
)
```

The explicit duration column matters: encoded segment duration, logical tied
duration, and measured performance duration answer different questions.

## Piano roll versus binary matrix

A piano roll is a visualization of note rows. A binary matrix is a computed
array whose rows are pitch positions and whose columns are time-grid steps.

| | Piano roll | Binary matrix |
| --- | --- | --- |
| Primary purpose | inspect and select notes | compute over a discrete pitch/time grid |
| Time | continuous plot coordinates | quantized by `resolution` |
| Pitch | note positions | full MIDI, cropped range, or chroma rows |
| Provenance | hover/selection can expose rows | must be requested and stored in matrix metadata |

## Create a binary matrix with context

Tutorial notebook:
[`binary_roundtrip.ipynb`](../../notebooks/binary_roundtrip.ipynb)
shows the representation rotation

```text
MEI → df_pitch / piano roll → binary + metadata → reconstructed notes → MEI highlight
```

so the matrix stays linked to musical identity rather than becoming an abstract
image.

```python
from camat.music_utils import create_binary_matrix_bundle

bundle = create_binary_matrix_bundle(
    df_pitch,
    source_name="score",
    resolution_method="auto",
    y_mode="minmax",
    include_provenance=True,
)

matrix = bundle.matrix
matrix_meta = bundle.meta
bundle.plot()
```

The metadata is not optional bookkeeping. It records the time resolution,
pitch-axis orientation and bounds, and—when enabled—the source rows behind
active cells. Store it with the matrix.

## Pattern search

Tutorial notebooks:

- [`binary_convolution_explained.ipynb`](../../notebooks/binary_convolution_explained.ipynb)
  — toy host/kernel placements and valid vs same padding on those windows,
  then sliding-window intuition, stride, and kernel scaling (time, pitch, or
  both) on Bach *Ein feste Burg*. Helpers: `convolution_map` /
  `score_kernel_at` in [pattern search](../api/pattern_search.md) and
  [binary convolution](../api/binary_convolution.md) plots;
- [`binary_pattern_search.ipynb`](../../notebooks/binary_pattern_search.ipynb)
  — motif, chord, and texture kernels with scaled-window search and piano-roll
  overlays.

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

`normalized_overlap` measures containment: extra host notes are not penalized,
and 1.0 does not imply equal matrices. `normalized_cross_correlation` considers
both active and inactive cells (and returns 0 for constant windows/kernels).
`padding="valid"` (default) keeps the kernel inside the host;
`padding="same"` zero-pads the border so the score map can match the host
size at stride 1. Stride and kernel scale factors remain the knobs for window
motion and size.

## Return results to the score

The overlay helpers combine match coordinates, binary-matrix provenance, note
rows, and MEI `xml:id` values. Verovio rendering can then highlight or crop the
corresponding notation. This closes the analytical loop without treating the
matrix as the edition itself.

The intended chain is:

```text
MEI -> df_pitch -> matrix + metadata -> matches -> source rows/xml:id -> score overlay
```

## Notebook coverage

| Notebook | Role |
| --- | --- |
| [`df_statistics.ipynb`](../../notebooks/df_statistics.ipynb) | DataFrame distributions |
| [`binary_roundtrip.ipynb`](../../notebooks/binary_roundtrip.ipynb) | MEI ↔ table ↔ binary rotation |
| [`binary_convolution_explained.ipynb`](../../notebooks/binary_convolution_explained.ipynb) | toy grids, valid vs same padding, then sliding-window convolution intuition |
| [`binary_pattern_search.ipynb`](../../notebooks/binary_pattern_search.ipynb) | motif / chord / texture search |

See the [notebook roadmap](../notebooks.md).
