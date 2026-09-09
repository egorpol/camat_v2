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
starts with a deterministic nine-note example, compares time resolutions and
pitch axes, then follows the representation rotation on a real score:

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
    measure_offsets=measure_offsets,  # pass explicitly for a filtered/renamed table
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

Time starts at zero, with onsets floored and note ends ceiled to the grid. The
matrix extends to the latest sounding note end. Notes crossing zero are clipped;
zero-duration events do not occupy cells. Automatic resolution uses the smallest
positive duration, which need not align every onset. Choose a manual grid when
you need control over that quantization.

To retain negative-onset pickups, use
`grid_notes, grid_offsets, source_origin = prepare_binary_timeline(df_pitch, measure_offsets)`
from `camat.binary_roundtrip`. It shifts notes and barlines together and keeps
the original onset in `Source Global Onset`; source time equals grid time plus
`source_origin`. For Bach's one-quarter pickup, grid time zero is source time
−1, and the first full barline is at grid time 1. Keep the original source table
and MEI for notation identity. Binary plots place MIDI 0 at the bottom and 127
at the top, independently of raw row storage order.

Roundtrip correctness has distinct meanings:

- **Cell coverage:** reconstruct contiguous runs and re-encode them on the same
  axes. Occupancy should agree exactly.
- **Note events:** touching repetitions and overlapping unisons merge, even on
  an exact grid. Splitting by voice prevents cross-voice merging but does not
  restore repeated-note boundaries within a voice.
- **Source identity:** provenance retains original rows and xml:ids. Binary
  values alone do not retain voices, spelling, articulation or notation choices.

Use `audit_binary_roundtrip(bundle)`, `compare_voice_roundtrips(bundle)` and
`describe_binary_span_sources(bundle)` from
[`camat.binary_roundtrip`](../api/binary_roundtrip.md) to inspect these differences.
Chroma folds octaves: use `binary_slice_to_df` for pitch-class spans and provenance
for original MIDI identities. `binary_matrix_to_df_from_meta` rejects chroma
because there is no unique octave reconstruction.

The notebook follows a search-selected matrix window back to highlighted notes
on complete original MEI pages, retaining all surrounding notes, rests, staves,
clefs and signatures. Its optional extension edits a **copy** of the toy matrix
and generates new notation via
music21, MusicXML and Verovio. Remove original provenance from edited metadata;
new notes must not inherit source xml:ids. Decode the edited array explicitly,
since a bundle's cached reconstructed DataFrame is not refreshed by array edits.

The initial nine-note example is also saved in
[`binary_roundtrip_voices.mei`](../../camat/examples/binary_roundtrip_voices.mei)
with three separate voices and the same note IDs as the table. The notebook
renders this source before demonstrating what occupancy loses.

### Search by voice and follow a match back to notation

`split_binary_voices(bundle)` creates separate voice bundles on identical
pitch/time axes, each with its own provenance. Pass each matrix to
`run_pattern_search` to use the existing metrics and augmentation policies
independently per voice. This prevents a melodic match from being assembled
across voices; it does not restore touching repeated-note boundaries within a
voice. Retaining those requires an event representation or additional onset
and offset channels, beyond a sustain-only binary matrix.

The roundtrip notebook works through two examples with
`find_binary_matches`, `plot_binary_search_trace` and `binary_match_sources`:
a merged-voice perfect fit that scores only 0.5 in every individual voice,
and recovery of a real score fragment. Each follows the same placement from a
heatmap to a binary window and then highlighted source notation. The trace
distinguishes all notes in the rectangle from notes contributing to occupied
query cells. Normalized overlap measures containment; extra host notes are
not penalized, and different placements can tie at 1.0.

Use `vrv_render_source_context(selection, mei_xml=source_mei)` to highlight the
contributing IDs while preserving the complete score on each selected page.
The contributor table can contain only two notes even though the rendered
context contains many more. `vrv_render_symbolic_selection` instead isolates
the selected notes using invisible spaces; that separate view is not the
complete score context used in this walkthrough.

In the notebook, section 7 copies a source fragment as a kernel and selects a
ranked search result. Section 8 interprets the result in its original notation.
Sections 9–10 optionally edit the toy pattern and search with that changed
query, showing the effect of missing query cells on normalized overlap.

## Pattern search

Tutorial notebooks:

- [`binary_convolution_explained.ipynb`](../../notebooks/binary_convolution_explained.ipynb)
  — toy host/kernel placements and valid vs same padding on those windows,
  then sliding-window intuition, stride, and kernel scaling (time, pitch, or
  both) on Bach *Ein feste Burg*. Helpers: `convolution_map` /
  `score_kernel_at` in [pattern search](../api/pattern_search.md) and
  [binary convolution](../api/binary_convolution.md) plots;
- [`binary_pattern_search.ipynb`](../../notebooks/binary_pattern_search.ipynb)
  — extract motif, chord, and texture kernels with their source coordinates;
  compare containment and correlation, merged and separate voices, and explicit
  augmentation recipes. Exclude the query's original passage, suppress nearby
  duplicate windows, then follow a ranked heatmap placement through the binary
  window and piano roll to highlighted notes in the complete original score.

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
