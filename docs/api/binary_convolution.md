---
title: Binary convolution
---

# Binary convolution

Teaching helpers for sliding-window overlap on binary pitch × time grids.
The score-map math lives in [pattern search](pattern_search.md)
(`convolution_map`, `score_kernel_at`, `pad_for_same`). This module holds the
toy kernel catalog and explainer plots used by
[`binary_convolution_explained.ipynb`](../../notebooks/binary_convolution_explained.ipynb).

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
