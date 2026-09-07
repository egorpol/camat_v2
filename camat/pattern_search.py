from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


__all__ = [
    "resize_kernel",
    "pad_for_same",
    "count_kernel_placements",
    "summarize_best",
    "top_matches",
    "apply_threshold",
    "finite_bounds",
    "plot_matplotlib_single",
    "plot_bokeh_single",
    "plot_kernel",
    "build_scale_variants",
    "compute_metrics_for_variant",
    "run_pattern_search",
]


def resize_kernel(arr: np.ndarray, scale_y: float, scale_x: float) -> np.ndarray:
    arr = np.asarray(arr, dtype=float)
    src_rows, src_cols = arr.shape
    tgt_rows = max(1, int(round(src_rows * float(scale_y))))
    tgt_cols = max(1, int(round(src_cols * float(scale_x))))
    if tgt_rows == src_rows and tgt_cols == src_cols:
        return arr.copy()
    y_grid = np.linspace(0, src_rows - 1, tgt_rows)
    x_grid = np.linspace(0, src_cols - 1, tgt_cols)
    y0 = np.floor(y_grid).astype(int)
    y1 = np.clip(y0 + 1, 0, src_rows - 1)
    wy = y_grid - y0
    x0 = np.floor(x_grid).astype(int)
    x1 = np.clip(x0 + 1, 0, src_cols - 1)
    wx = x_grid - x0
    top = (1 - wx) * arr[y0[:, None], x0] + wx * arr[y0[:, None], x1]
    bottom = (1 - wx) * arr[y1[:, None], x0] + wx * arr[y1[:, None], x1]
    return (1 - wy)[:, None] * top + wy[:, None] * bottom


def summarize_best(name: str, data: np.ndarray, labels_y: List, labels_x: List) -> Optional[Tuple[float, int, int]]:
    finite_mask = np.isfinite(data)
    if not finite_mask.any():
        print(f"{name}: no finite values to summarise.")
        return None
    flat_index = np.nanargmax(data)
    r, c = divmod(int(flat_index), data.shape[1])
    print(f"{name} best: {data[r, c]:.3f} at top-left (row={labels_y[r]}, col={labels_x[c]})")
    return float(data[r, c]), int(r), int(c)


def top_matches(name: str, data: np.ndarray, labels_y: List, labels_x: List, top_n: Optional[int], threshold: Optional[float] = None) -> List[Tuple[float, int, int]]:
    if top_n is None or top_n <= 0:
        return []
    flat = data.reshape(-1)
    mask = np.isfinite(flat)
    if threshold is not None:
        mask &= flat >= threshold
    indices = np.nonzero(mask)[0]
    if indices.size == 0:
        print(f"{name}: no entries meet the threshold.")
        return []
    ranked = indices[np.argsort(flat[indices])[::-1]]
    limit = min(int(top_n), ranked.size)
    results: List[Tuple[float, int, int]] = []
    print(f"{name} top {limit} positions:")
    for idx in ranked[:limit]:
        val = float(flat[idx])
        r, c = divmod(int(idx), data.shape[1])
        print(f"  score={val:.3f} at row={labels_y[r]}, col={labels_x[c]}")
        results.append((val, r, c))
    return results


def apply_threshold(data: np.ndarray, threshold: Optional[float]):
    if threshold is None:
        return data
    return np.where(data >= threshold, data, np.nan)


def finite_bounds(data: np.ndarray) -> Tuple[float, float]:
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 0.0, 1.0
    low = float(np.min(finite))
    high = float(np.max(finite))
    if low == high:
        high = low + 1e-9
    return low, high


def plot_matplotlib_single(title: str, data: np.ndarray, *, threshold: Optional[float] = None, color_bounds: Optional[Tuple[float, float]] = None, cmap: str = "viridis") -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 6))
    masked = apply_threshold(data, threshold)
    if color_bounds is None:
        vmin, vmax = None, None
    else:
        vmin, vmax = color_bounds
    im = ax.imshow(masked, cmap=cmap, origin='upper', aspect='auto', vmin=vmin, vmax=vmax)
    ax.set_title(title)
    ax.set_xlabel('time offset (columns)')
    ax.set_ylabel('pitch offset (rows)')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    plt.show()


_BOKEH_NOTEBOOK_INITIALIZED = False


def plot_bokeh_single(title: str, data: np.ndarray, *, threshold: Optional[float] = None, color_bounds: Optional[Tuple[float, float]] = None) -> None:
    global _BOKEH_NOTEBOOK_INITIALIZED
    # Initialize inline output once when running in a notebook
    if not _BOKEH_NOTEBOOK_INITIALIZED:
        try:
            from IPython import get_ipython  # type: ignore
            ip = get_ipython()
        except Exception:
            ip = None
        if ip is not None:
            try:
                from bokeh.io import output_notebook
                output_notebook(hide_banner=True)
                _BOKEH_NOTEBOOK_INITIALIZED = True
            except Exception:
                pass
    from bokeh.plotting import figure, show
    from bokeh.models import LinearColorMapper, ColorBar
    from bokeh.palettes import Viridis256

    masked = apply_threshold(data, threshold)
    if color_bounds is None:
        low, high = finite_bounds(masked)
    else:
        low, high = color_bounds
    fig = figure(
        title=title,
        x_range=(0, masked.shape[1]),
        y_range=(0, masked.shape[0]),
        width=900,
        height=600,
        tools='pan,wheel_zoom,reset,save',
    )
    mapper = LinearColorMapper(palette=Viridis256, low=low, high=high)
    fig.image(image=[np.flipud(masked)], x=0, y=0, dw=masked.shape[1], dh=masked.shape[0], color_mapper=mapper)
    fig.add_layout(ColorBar(color_mapper=mapper), 'right')
    fig.xaxis.axis_label = 'time offset (columns)'
    fig.yaxis.axis_label = 'pitch offset (rows, top=high)'
    show(fig)


def plot_kernel(title: str, kernel: np.ndarray, *, backend: str = "plt", cmap: str = "viridis") -> None:
    if backend in ("plt", "both"):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 6))
        im = ax.imshow(kernel, cmap=cmap, origin='upper', aspect='auto')
        ax.set_title(title)
        ax.set_xlabel('kernel columns')
        ax.set_ylabel('kernel rows')
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        plt.show()
    if backend in ("bokeh", "both"):
        from bokeh.plotting import figure, show
        from bokeh.models import LinearColorMapper, ColorBar
        from bokeh.palettes import Viridis256

        low, high = finite_bounds(kernel)
        fig = figure(
            title=title,
            x_range=(0, kernel.shape[1]),
            y_range=(0, kernel.shape[0]),
            width=900,
            height=600,
            tools='pan,wheel_zoom,reset,save',
        )
        mapper = LinearColorMapper(palette=Viridis256, low=low, high=high)
        fig.image(image=[np.flipud(kernel)], x=0, y=0, dw=kernel.shape[1], dh=kernel.shape[0], color_mapper=mapper)
        fig.add_layout(ColorBar(color_mapper=mapper), 'right')
        fig.xaxis.axis_label = 'kernel columns'
        fig.yaxis.axis_label = 'kernel rows (top=high)'
        show(fig)


def pad_for_same(matrix: np.ndarray, kernel: np.ndarray) -> Tuple[np.ndarray, int, int]:
    """Zero-pad so valid convolution on the result has the host shape at stride 1.

    Output cell ``(i, j)`` corresponds to kernel top-left at host
    ``(i - pad_y, j - pad_x)``, which may be negative (kernel hangs off the edge).
    Missing cells are silence (0).
    """
    M = np.asarray(matrix, dtype=float)
    K = np.asarray(kernel, dtype=float)
    if M.ndim != 2 or K.ndim != 2:
        raise ValueError("matrix and kernel must be 2D.")
    r, c = K.shape
    pad_y = r // 2
    pad_x = c // 2
    Mp = np.pad(M, ((pad_y, r - 1 - pad_y), (pad_x, c - 1 - pad_x)))
    return Mp, int(pad_y), int(pad_x)


def _normalize_padding(padding: str) -> str:
    mode = str(padding).strip().lower()
    if mode not in {"valid", "same"}:
        raise ValueError("padding must be 'valid' or 'same'.")
    return mode


def count_kernel_placements(
    host_shape: Tuple[int, int],
    kernel_shape: Tuple[int, int],
    *,
    padding: str = "valid",
    stride_y: int = 1,
    stride_x: int = 1,
) -> Tuple[int, int, int]:
    """Return ``(n_row, n_col, n_total)`` kernel top-lefts for this padding/stride."""
    mode = _normalize_padding(padding)
    H, W = (int(host_shape[0]), int(host_shape[1]))
    h, w = (int(kernel_shape[0]), int(kernel_shape[1]))
    sy = max(1, int(stride_y))
    sx = max(1, int(stride_x))
    if mode == "valid":
        n_row = max(0, H - h + 1)
        n_col = max(0, W - w + 1)
    else:
        n_row = H
        n_col = W
    if n_row <= 0 or n_col <= 0:
        return 0, 0, 0
    n_row_s = len(range(0, n_row, sy))
    n_col_s = len(range(0, n_col, sx))
    return n_row_s, n_col_s, n_row_s * n_col_s


def _host_axis_labels(full_labels: List, positions: List[int], pad: int) -> List:
    n = len(full_labels)
    labels: List = []
    for pos in positions:
        host_i = int(pos) - int(pad)
        if 0 <= host_i < n:
            labels.append(full_labels[host_i])
        else:
            labels.append(host_i)
    return labels


def build_scale_variants(kernel_scale_axes: List[str], kernel_scale_factors: List[float]) -> List[Dict[str, float]]:
    scale_variants: List[Dict[str, float]] = []
    seen_scales: set[Tuple[float, float]] = set()
    for axis in kernel_scale_axes:
        axis_norm = str(axis).lower()
        if axis_norm not in {"x", "y", "both"}:
            raise ValueError(f"Unsupported axis {axis!r} in KERNEL_SCALE_AXES; use 'x', 'y', or 'both'.")
        for factor in kernel_scale_factors:
            factor = float(factor)
            if factor <= 0:
                raise ValueError(f"Scale factor must be positive; received {factor}.")
            scale_y = factor if axis_norm in {"y", "both"} else 1.0
            scale_x = factor if axis_norm in {"x", "both"} else 1.0
            key = (round(scale_y, 6), round(scale_x, 6))
            if key in seen_scales:
                continue
            seen_scales.add(key)
            label = f"axis={axis_norm}, factor={factor:g}, scale_y={scale_y:.3f}, scale_x={scale_x:.3f}"
            scale_variants.append({"axis": axis_norm, "factor": factor, "scale_y": scale_y, "scale_x": scale_x, "label": label})
    return scale_variants


def compute_metrics_for_variant(
    matrix: np.ndarray,
    scaled_kernel: np.ndarray,
    *,
    stride_y: int = 1,
    stride_x: int = 1,
    metrics: List[str] = None,
    padding: str = "valid",
) -> Tuple[Dict[str, np.ndarray], Dict[str, pd.DataFrame], List[int], List[int], int, int, np.ndarray]:
    metrics = list(metrics or [])
    mode = _normalize_padding(padding)
    work = np.asarray(matrix, dtype=float)
    kernel = np.asarray(scaled_kernel, dtype=float)
    pad_y = pad_x = 0
    if mode == "same":
        work, pad_y, pad_x = pad_for_same(work, kernel)
    elif kernel.shape[0] > work.shape[0] or kernel.shape[1] > work.shape[1]:
        raise ValueError("Scaled kernel is larger than the source matrix.")

    window_shape = kernel.shape
    out_rows = work.shape[0] - window_shape[0] + 1
    out_cols = work.shape[1] - window_shape[1] + 1
    if out_rows <= 0 or out_cols <= 0:
        raise ValueError("Kernel cannot slide within the source matrix.")

    windows = np.lib.stride_tricks.sliding_window_view(work, window_shape)
    conv_scores_full = (windows * kernel).sum(axis=(-2, -1))

    row_positions = list(range(0, out_rows, max(1, int(stride_y))))
    col_positions = list(range(0, out_cols, max(1, int(stride_x))))

    metric_arrays: Dict[str, np.ndarray] = {}
    metric_dfs: Dict[str, pd.DataFrame] = {}

    if 'normalized_overlap' in metrics:
        kernel_weight = float(scaled_kernel.sum())
        if kernel_weight != 0.0:
            conv_norm_full = conv_scores_full / kernel_weight
        else:
            conv_norm_full = conv_scores_full.astype(float)
        conv_norm = conv_norm_full[np.ix_(row_positions, col_positions)]
        metric_arrays['normalized_overlap'] = conv_norm
        metric_dfs['normalized_overlap'] = pd.DataFrame(conv_norm)

    needs_cross = any(m in metrics for m in ('cross_covariance', 'normalized_cross_correlation'))
    if needs_cross:
        windows_flat = windows.reshape(out_rows, out_cols, -1)
        kernel_flat = scaled_kernel.reshape(-1)
        kernel_mean = kernel_flat.mean()
        kernel_zero_mean = kernel_flat - kernel_mean
        kernel_norm_val = float(np.linalg.norm(kernel_zero_mean))
        window_means = windows_flat.mean(axis=2, keepdims=True)
        windows_zero_mean = windows_flat - window_means
        window_norms = np.linalg.norm(windows_zero_mean, axis=2)
        cross_cov_full = np.tensordot(windows_zero_mean, kernel_zero_mean, axes=([2], [0]))

        if 'cross_covariance' in metrics:
            cross_cov = cross_cov_full[np.ix_(row_positions, col_positions)]
            metric_arrays['cross_covariance'] = cross_cov
            metric_dfs['cross_covariance'] = pd.DataFrame(cross_cov)

        if 'normalized_cross_correlation' in metrics:
            denominator = window_norms * kernel_norm_val
            norm_cross_full = np.divide(
                cross_cov_full,
                denominator,
                out=np.zeros_like(cross_cov_full),
                where=denominator > 0,
            )
            norm_cross = norm_cross_full[np.ix_(row_positions, col_positions)]
            metric_arrays['normalized_cross_correlation'] = norm_cross
            metric_dfs['normalized_cross_correlation'] = pd.DataFrame(norm_cross)

    return metric_arrays, metric_dfs, row_positions, col_positions, pad_y, pad_x, work


def run_pattern_search(
    matrix_source: pd.DataFrame | np.ndarray,
    kernel_source: pd.DataFrame | np.ndarray,
    *,
    metrics_to_run: List[str],
    stride_y: int = 1,
    stride_x: int = 1,
    kernel_scale_factors: List[float] = (1.0,),
    kernel_scale_axes: List[str] = ("x",),
    binarize_scaled_kernel: bool = True,
    binarize_threshold: float = 0.5,
    share_y_scaling: bool = True,
    plot_thresholds: Optional[Dict[str, Optional[float]]] = None,
    backend: str = "plt",
    mpl_cmap: str = "viridis",
    plot_scaled_kernels: bool = False,
    top_n_matches: Optional[int] = 20,
    padding: str = "valid",
) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], Dict[str, np.ndarray], Optional[str], Optional[pd.DataFrame]]:
    """Slide ``kernel_source`` over ``matrix_source`` and score each placement.

    ``padding="valid"`` (default) keeps only placements where the kernel fits
    inside the host. ``padding="same"`` zero-pads the host so the score map can
    match the host size at stride 1; hanging cells are silence (0). Result
    index/column labels are host top-left coordinates and may be negative
    under ``"same"``.
    """
    padding = _normalize_padding(padding)
    if isinstance(matrix_source, pd.DataFrame):
        matrix = matrix_source.to_numpy(dtype=float)
        row_labels_full = list(matrix_source.index)
        col_labels_full = list(matrix_source.columns)
    else:
        matrix = np.asarray(matrix_source, dtype=float)
        if matrix.ndim != 2:
            raise ValueError('matrix_source must be a 2D table or array.')
        row_labels_full = list(range(matrix.shape[0]))
        col_labels_full = list(range(matrix.shape[1]))

    if isinstance(kernel_source, pd.DataFrame):
        kernel_array = kernel_source.to_numpy(dtype=float)
    else:
        kernel_array = np.asarray(kernel_source, dtype=float)

    if kernel_array.ndim != 2:
        raise ValueError('kernel_source must be a 2D structure to act as a kernel.')
    if kernel_array.size == 0:
        raise ValueError('kernel_source is empty; draw a pattern before running the analysis.')

    available_metrics = {
        'normalized_overlap': {'label': 'Normalised overlap'},
        'cross_covariance': {'label': 'Cross-covariance'},
        'normalized_cross_correlation': {'label': 'Normalised cross-correlation'},
    }
    selected_metrics = [m for m in metrics_to_run if m in available_metrics]
    if not selected_metrics:
        raise ValueError('metrics_to_run does not include any supported metrics.')

    scale_variants = build_scale_variants(list(kernel_scale_axes), list(kernel_scale_factors))

    all_results: Dict[str, Dict[str, pd.DataFrame]] = {}
    scaled_kernels: Dict[str, np.ndarray] = {}
    last_variant_key: Optional[str] = None
    last_conv_raw_df: Optional[pd.DataFrame] = None

    shared_bounds: Dict[str, List[float]] = {m: [np.inf, -np.inf] for m in available_metrics.keys()}
    deferred_plots: List[Dict[str, object]] = []

    for variant in scale_variants:
        scale_y = float(variant['scale_y'])
        scale_x = float(variant['scale_x'])
        variant_key = str(variant['label'])
        scaled_kernel = resize_kernel(kernel_array, scale_y, scale_x)
        if binarize_scaled_kernel:
            _thr = float(binarize_threshold)
            scaled_kernel = (scaled_kernel >= _thr).astype(float)

        if plot_scaled_kernels:
            plot_kernel(f"Scaled kernel ({variant_key})", scaled_kernel, backend=backend, cmap=mpl_cmap)

        if padding == "valid" and (
            scaled_kernel.shape[0] > matrix.shape[0] or scaled_kernel.shape[1] > matrix.shape[1]
        ):
            # Skip variants larger than source
            continue

        metric_arrays, metric_dfs, row_positions, col_positions, pad_y, pad_x, work = compute_metrics_for_variant(
            matrix,
            scaled_kernel,
            stride_y=stride_y,
            stride_x=stride_x,
            metrics=selected_metrics,
            padding=padding,
        )

        row_labels = _host_axis_labels(row_labels_full, row_positions, pad_y)
        col_labels = _host_axis_labels(col_labels_full, col_positions, pad_x)

        for metric_key in selected_metrics:
            metric_label = available_metrics[metric_key]['label']
            data = metric_arrays.get(metric_key)
            if data is None:
                continue
            threshold = None if plot_thresholds is None else plot_thresholds.get(metric_key)

            share_scale = bool(share_y_scaling) and len(scale_variants) > 1
            if share_scale:
                masked = apply_threshold(data, threshold)
                if np.isfinite(masked).any():
                    low, high = finite_bounds(masked)
                    bounds = shared_bounds.get(metric_key)
                    if bounds is not None:
                        bounds[0] = min(bounds[0], low)
                        bounds[1] = max(bounds[1], high)
                deferred_plots.append({
                    'metric_key': metric_key,
                    'metric_label': metric_label,
                    'data': data,
                    'threshold': threshold,
                    'row_labels': row_labels,
                    'col_labels': col_labels,
                })
            else:
                if backend == 'plt':
                    plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=None, cmap=mpl_cmap)
                elif backend == 'bokeh':
                    plot_bokeh_single(metric_label, data, threshold=threshold, color_bounds=None)
                elif backend == 'both':
                    plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=None, cmap=mpl_cmap)
                    plot_bokeh_single(metric_label, data, threshold=threshold, color_bounds=None)
                elif backend == 'none':
                    pass
                else:
                    print(f"Unknown backend {backend!r}. Defaulting to Matplotlib.")
                    plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=None, cmap=mpl_cmap)

                summarize_best(metric_label, data, row_labels, col_labels)
                top_matches(metric_label, data, row_labels, col_labels, top_n_matches, threshold)

        # Convert metric arrays to DataFrames with labels for return
        labeled_metric_dfs: Dict[str, pd.DataFrame] = {}
        for k, arr in metric_arrays.items():
            labeled_metric_dfs[k] = pd.DataFrame(arr, index=row_labels, columns=col_labels)

        all_results[variant_key] = labeled_metric_dfs
        scaled_kernels[variant_key] = scaled_kernel
        last_variant_key = variant_key

        # Save last raw conv for convenience (same working matrix as the metrics)
        if 'normalized_overlap' in metric_arrays:
            conv_scores_full = np.lib.stride_tricks.sliding_window_view(work, scaled_kernel.shape)
            conv_scores_full = (conv_scores_full * scaled_kernel).sum(axis=(-2, -1))
            conv_raw = conv_scores_full[np.ix_(row_positions, col_positions)]
            last_conv_raw_df = pd.DataFrame(conv_raw, index=row_labels, columns=col_labels)

    # Deferred plots with shared color scale
    if bool(share_y_scaling) and len(scale_variants) > 1 and deferred_plots:
        final_bounds: Dict[str, Tuple[float, float]] = {}
        for m, (lo, hi) in shared_bounds.items():
            if np.isfinite(lo) and np.isfinite(hi) and lo < hi:
                final_bounds[m] = (float(lo), float(hi))
        for item in deferred_plots:
            metric_key = str(item['metric_key'])
            metric_label = str(item['metric_label'])
            data = np.asarray(item['data'])
            threshold = item['threshold']
            bounds = final_bounds.get(metric_key)
            if backend == 'plt':
                plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=bounds, cmap=mpl_cmap)
            elif backend == 'bokeh':
                plot_bokeh_single(metric_label, data, threshold=threshold, color_bounds=bounds)
            elif backend == 'both':
                plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=bounds, cmap=mpl_cmap)
                plot_bokeh_single(metric_label, data, threshold=threshold, color_bounds=bounds)
            elif backend == 'none':
                pass
            else:
                print(f"Unknown backend {backend!r}. Defaulting to Matplotlib.")
                plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=bounds, cmap=mpl_cmap)

            summarize_best(metric_label, data, item['row_labels'], item['col_labels'])
            top_matches(metric_label, data, item['row_labels'], item['col_labels'], top_n_matches, threshold)

    return all_results, scaled_kernels, last_variant_key, last_conv_raw_df


