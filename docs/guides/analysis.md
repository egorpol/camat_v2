---
title: Analyse representations
---

# Analyse representations

CAMAT has two complementary analysis layers:

1. **DataFrame analysis**, which works with musical columns and MEI identities;
2. **matrix analysis**, which discretizes pitch and time for image-like pattern
   operations.

Start with the least transformed representation that answers the question.

## DataFrame analysis

The note table is suitable for grouping, filtering, descriptive statistics,
and sequential analyses. CAMAT includes helpers for:

- pitch and pitch-class distributions;
- metric, logical, or externally supplied performed-duration distributions;
- melodic intervals and successive-pitch transitions;
- onset positions within measures;
- filtering and piano-roll display.

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

`run_pattern_search(...)` compares a source matrix with a smaller kernel using
one or more similarity metrics. Kernels may be extracted from another matrix or
drawn interactively with `binary_matrix_designer(...)`.

```python
from camat import run_pattern_search

all_results, scaled_kernels, variant, last_result = run_pattern_search(
    matrix,
    kernel,
    metrics_to_run=["normalized_overlap"],
    backend="none",
)
```

Meaningful comparison requires compatible pitch orientation and time
resolution. Scaling a kernel is an analytical decision, not a display option.

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

The current notebooks introduce conversion and duration semantics. A dedicated
end-to-end parsing notebook and a matrix-analysis notebook are the next two
tutorials in the [notebook roadmap](../notebooks.md).

