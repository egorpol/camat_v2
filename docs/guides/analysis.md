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
[`df_statistics.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/df_statistics.ipynb)
(CMN only). It parses one MEI file for itself and shows:

- pitch and pitch-class distributions;
- metric or logical duration distributions (see also
  [`duration_semantics_examples.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/duration_semantics_examples.ipynb));
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
[`binary_roundtrip.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/binary_roundtrip.ipynb)
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

Tutorial notebook:
[`binary_pattern_search.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/binary_pattern_search.ipynb)
searches Bach with motif, chord, and texture kernels, including time-scale
modulation of the search window.

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

| Notebook | Role |
| --- | --- |
| [`df_statistics.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/df_statistics.ipynb) | DataFrame distributions |
| [`binary_roundtrip.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/binary_roundtrip.ipynb) | MEI ↔ table ↔ binary rotation |
| [`binary_pattern_search.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/binary_pattern_search.ipynb) | motif / chord / texture search |

See the [notebook roadmap](../notebooks.md).
