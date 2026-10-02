---
title: Binary convolution
---

# Binary convolution

Teaching helpers for sliding-window overlap on binary pitch × time grids.
The score-map math lives in [pattern search](pattern_search.md)
(`convolution_map`, `score_kernel_at`, `pad_for_same`). This module holds the
example-pattern catalog (`EXAMPLE_PATTERNS`) and explainer plots used by
[`binary_convolution_explained.ipynb`](../../notebooks/binary_convolution_explained.ipynb).

`resolve_example_pattern` selects a catalog pattern and `show_example_overview`
plots it against an example passage. `show_musical_overlap_example` connects
notation with exact, missing-note and added-accompaniment matches;
`show_rhythmic_augmentation_example` and `show_pitch_interval_example` explain
duration changes and pitch-interval scaling around a fixed anchor before the
grid comparisons. Their notation uses an opaque white background and black
captions for readability in dark notebook themes.

Padding plots distinguish a pattern fully inside the passage (`valid`) from
placements over an artificial empty border (`same`). Stride plots label the
actual candidate starts and their spacing on the passage grid.

When updating code from 0.2.4, replace `TOY_HOST_SHAPE` with
`EXAMPLE_PASSAGE_SHAPE`, `TOY_KERNELS` with `EXAMPLE_PATTERNS`,
`resolve_toy_kernel` with `resolve_example_pattern`, and `show_toy_overview`
with `show_example_overview` in imports and calls.

`binary_score_details` reports every cell's contribution and the intermediate
counts, means and norms behind normalized overlap, cross-covariance and
normalized cross-correlation. `plot_binary_score_explanation` aligns the query,
window, product and shared/extra/missing-cell classifications for small teaching
examples, as used in §4 of the pattern-search methods notebook.

`plot_kernel_scales` accepts the search API's pitch, time, sampling, rounding,
and binarization controls. `plot_kernel_augmentations` compares named recipes
and returns their kernels for further experiments:

```python
from camat.binary_convolution import plot_kernel_augmentations

kernels = plot_kernel_augmentations(
    kernel,
    {
        "Pitch lines": {"pitch_mode": "intervals", "time_mode": "events"},
        "Pitch bands": {"pitch_mode": "stretch", "method": "nearest"},
        "Coverage weights": {"pitch_mode": "intervals", "method": "area"},
    },
    scale_y=1.5,
    scale_x=0.75,
    binarize_scaled_kernel=False,
)
```

::: camat.binary_convolution
