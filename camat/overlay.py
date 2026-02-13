from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from bokeh.io import show as bokeh_show
from bokeh.models import ColumnDataSource, HoverTool
from bokeh.palettes import Viridis256 as _Viridis256

from .music_utils import draw_piano_roll


__all__ = [
    "select_metric_df",
    "kernel_from_variants",
    "compute_top_matches_df",
    "build_match_records",
    "build_overlay_source",
    "overlay_top_matches_on_piano_roll",
]


def select_metric_df(
    pattern_search_results: Dict[str, Dict[str, pd.DataFrame]],
    metric_key: str,
    *,
    variant_key: Optional[str] = None,
) -> Tuple[str, pd.DataFrame]:
    """
    Pick a metric DataFrame from pattern search results.

    When variant_key is None, the most recently inserted variant is used.
    """
    if not pattern_search_results:
        raise ValueError("pattern_search_results is empty.")
    chosen_variant = variant_key
    if chosen_variant is None:
        # dict preserves insertion order in modern Python; use last inserted
        chosen_variant = next(reversed(pattern_search_results))
    metrics = pattern_search_results.get(chosen_variant, {})
    df = metrics.get(metric_key)
    if df is None:
        available = ", ".join(sorted(metrics.keys())) or "<none>"
        raise ValueError(
            f"Metric {metric_key!r} not present for variant {chosen_variant!r}. Available: {available}"
        )
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)
    return chosen_variant, df


def kernel_from_variants(
    pattern_search_kernels: Dict[str, Any],
    variant_key: str,
    default_kernel: Any,
) -> np.ndarray:
    """
    Return kernel array for the selected variant, or fallback to default.
    """
    src = pattern_search_kernels.get(variant_key, default_kernel)
    if hasattr(src, "to_numpy"):
        return np.asarray(src.to_numpy(dtype=float))
    return np.asarray(src, dtype=float)


def compute_top_matches_df(
    conv_df: pd.DataFrame,
    *,
    top_n: int = 5,
    min_score: Optional[float] = None,
    score_quantile: Optional[float] = None,
) -> pd.DataFrame:
    """
    Flatten a convolution/metric DataFrame and return a sorted DataFrame with
    columns ['row_idx', 'col_idx', 'score_norm'], filtered by optional
    min_score or quantile threshold, and limited to top_n.
    """
    if top_n is None or int(top_n) <= 0:
        raise ValueError("top_n must be a positive integer.")

    values = pd.DataFrame(conv_df).replace([np.inf, -np.inf], np.nan)
    flat = (
        values.stack(dropna=True)
        .reset_index()
        .rename(columns={"level_0": "row_idx", "level_1": "col_idx", 0: "score_norm"})
    )
    flat = flat[np.isfinite(flat["score_norm"])]
    if flat.empty:
        raise ValueError("No finite scores available in conv_df.")

    # Apply thresholds
    if score_quantile is not None:
        q = float(score_quantile)
        if not (0.0 <= q <= 1.0):
            raise ValueError("score_quantile must be within [0, 1].")
        q_threshold = float(flat["score_norm"].quantile(q))
        flat = flat[flat["score_norm"] >= q_threshold]

    if min_score is not None:
        flat = flat[flat["score_norm"] >= float(min_score)]

    if flat.empty:
        raise ValueError("No scores meet the selection criteria.")

    flat = flat.sort_values("score_norm", ascending=False).head(int(top_n)).reset_index(drop=True)
    return flat


def _midi_from_row(row_index: int, *, row_order: str, y_min: int, y_max: int) -> int:
    idx = int(row_index)
    if row_order == "low_to_high":
        return int(y_min + idx)
    return int(y_max - idx)


def build_match_records(
    top_matches_df: pd.DataFrame,
    *,
    kernel_array: np.ndarray,
    meta: Dict[str, Any],
    conv_raw_df: Optional[pd.DataFrame] = None,
) -> List[Dict[str, Any]]:
    """
    Convert top-match grid indices into time/pitch rectangles using meta and kernel size.
    """
    kernel = np.asarray(kernel_array, dtype=float)
    kernel_rows, kernel_cols = kernel.shape
    resolution = float(meta["resolution"])  # required in meta
    row_order = str(meta.get("row_order", "low_to_high")).lower()
    y_min = int(meta.get("y_min", 0))
    y_max = int(meta.get("y_max", y_min))

    records: List[Dict[str, Any]] = []
    for rank, row in enumerate(top_matches_df.itertuples(index=False), start=1):
        r = int(row.row_idx)
        c = int(row.col_idx)
        r_end = r + kernel_rows - 1
        midi_first = _midi_from_row(r, row_order=row_order, y_min=y_min, y_max=y_max)
        midi_last = _midi_from_row(r_end, row_order=row_order, y_min=y_min, y_max=y_max)
        midi_low = min(midi_first, midi_last)
        midi_high = max(midi_first, midi_last)
        t0 = c * resolution
        t1 = (c + kernel_cols) * resolution
        if conv_raw_df is not None:
            try:
                score_raw = float(conv_raw_df.loc[r, c])
            except Exception:
                score_raw = float("nan")
        else:
            score_raw = float("nan")

        score_norm = float(getattr(row, "score_norm"))
        records.append({
            "rank": rank,
            "row_idx": r,
            "col_idx": c,
            "score_norm": score_norm,
            "score_raw": score_raw,
            "time_start": float(t0),
            "time_end": float(t1),
            "x_center": float((t0 + t1) / 2.0),
            "width": float(t1 - t0),
            "midi_low": int(midi_low),
            "midi_high": int(midi_high),
            "y_center": float((midi_low + midi_high) / 2.0),
            "height": float((midi_high - midi_low) + 1.0),
        })
    return records


def build_overlay_source(
    match_records: Sequence[Dict[str, Any]],
    *,
    palette: Sequence[str] = _Viridis256,
) -> Tuple[ColumnDataSource, List[float], List[str]]:
    """
    Build a Bokeh ColumnDataSource and corresponding colors for match records.
    Returns (source, norm_values, colors).
    """
    if not match_records:
        raise ValueError("match_records is empty.")

    scores = np.array([float(rec["score_norm"]) for rec in match_records], dtype=float)
    finite_mask = np.isfinite(scores)
    if not finite_mask.any():
        raise ValueError("All normalized scores are non-finite; cannot determine colors.")
    score_min = float(np.nanmin(scores[finite_mask]))
    score_max = float(np.nanmax(scores[finite_mask]))

    def _norm(val: float) -> float:
        if not np.isfinite(val):
            return 0.0
        if score_max > score_min:
            return (val - score_min) / (score_max - score_min)
        return 1.0

    norm_values: List[float] = [_norm(v) for v in scores.tolist()]
    pal_size = len(palette)
    colors: List[str] = [
        palette[min(pal_size - 1, max(0, int(round(nv * (pal_size - 1)))))] for nv in norm_values
    ]

    src = ColumnDataSource({
        "x_center": [rec["x_center"] for rec in match_records],
        "y_center": [rec["y_center"] for rec in match_records],
        "width": [rec["width"] for rec in match_records],
        "height": [rec["height"] for rec in match_records],
        "time_start": [rec["time_start"] for rec in match_records],
        "time_end": [rec["time_end"] for rec in match_records],
        "midi_low": [rec["midi_low"] for rec in match_records],
        "midi_high": [rec["midi_high"] for rec in match_records],
        "score_norm": [rec["score_norm"] for rec in match_records],
        "score_raw": [rec["score_raw"] for rec in match_records],
        "rank": [rec["rank"] for rec in match_records],
        "row_idx": [rec["row_idx"] for rec in match_records],
        "col_idx": [rec["col_idx"] for rec in match_records],
        "color": colors,
        "norm_value": norm_values,
    })
    return src, norm_values, colors


def overlay_top_matches_on_piano_roll(
    df_notes: pd.DataFrame,
    conv_df: pd.DataFrame,
    *,
    kernel_source: pd.DataFrame | np.ndarray,
    meta: Dict[str, Any],
    measure_offsets: Optional[List[float]] = None,
    top_n: int = 5,
    min_score: Optional[float] = None,
    score_quantile: Optional[float] = None,
    palette: Sequence[str] = _Viridis256,
    fill_alpha: float = 0.25,
    plot_width: int = 1200,
    plot_height: int = 800,
    dpi: float = 100.0,
    zoom_drag_dim: str = "both",
    zoom_wheel_dim: str = "width",
    conv_raw_df: Optional[pd.DataFrame] = None,
    show_kernel: bool = False,
    kernel_color: str = "red",
    kernel_alpha: float = 0.8,
    show: bool = True,
):
    """
    Render the top matches overlay on a Bokeh piano roll and return (plot, df_matches).
    """
    variant_top = compute_top_matches_df(
        conv_df,
        top_n=int(top_n),
        min_score=min_score,
        score_quantile=score_quantile,
    )

    kernel_array = np.asarray(kernel_source.to_numpy(dtype=float)) if hasattr(kernel_source, "to_numpy") else np.asarray(kernel_source, dtype=float)
    match_records = build_match_records(
        variant_top,
        kernel_array=kernel_array,
        meta=meta,
        conv_raw_df=conv_raw_df,
    )
    overlay_source, norm_values, _ = build_overlay_source(match_records, palette=palette)

    # Prepare kernel visualization data if requested
    kernel_rect_data = []
    if show_kernel and kernel_array.size > 0:
        kernel_rows, kernel_cols = kernel_array.shape
        resolution = float(meta["resolution"])
        row_order = str(meta.get("row_order", "low_to_high")).lower()
        y_min = int(meta.get("y_min", 0))
        y_max = int(meta.get("y_max", y_min))

        for rec in match_records:
            row_start = int(rec["row_idx"])
            col_start = int(rec["col_idx"])
            time_start = float(rec["time_start"])

            # Create rectangles for each kernel cell that has a value > 0
            for kr in range(kernel_rows):
                for kc in range(kernel_cols):
                    if kernel_array[kr, kc] > 0:
                        row_idx = row_start + kr
                        midi_value = _midi_from_row(
                            row_idx,
                            row_order=row_order,
                            y_min=y_min,
                            y_max=y_max,
                        )
                        kernel_time = time_start + (kc + 0.5) * resolution

                        kernel_rect_data.append({
                            'x': kernel_time,
                            'y': float(midi_value),
                            'width': resolution,
                            'height': 1.0,
                            'rank': rec["rank"],
                            'row_idx': row_start + kr,
                            'col_idx': col_start + kc,
                            'score_norm': float(rec["score_norm"]),
                            'score_raw': float(rec["score_raw"]),
                            'time_start': kernel_time - (resolution / 2.0),
                            'time_end': kernel_time + (resolution / 2.0),
                            'midi_low': float(midi_value),
                            'midi_high': float(midi_value),
                            'kernel_value': float(kernel_array[kr, kc]),
                        })

    # Create kernel source if we have kernel data
    kernel_source = None
    if kernel_rect_data:
        kernel_source = ColumnDataSource({
            'x': [r['x'] for r in kernel_rect_data],
            'y': [r['y'] for r in kernel_rect_data],
            'width': [r['width'] for r in kernel_rect_data],
            'height': [r['height'] for r in kernel_rect_data],
            'rank': [r['rank'] for r in kernel_rect_data],
            'row_idx': [r['row_idx'] for r in kernel_rect_data],
            'col_idx': [r['col_idx'] for r in kernel_rect_data],
            'score_norm': [r['score_norm'] for r in kernel_rect_data],
            'score_raw': [r['score_raw'] for r in kernel_rect_data],
            'time_start': [r['time_start'] for r in kernel_rect_data],
            'time_end': [r['time_end'] for r in kernel_rect_data],
            'midi_low': [r['midi_low'] for r in kernel_rect_data],
            'midi_high': [r['midi_high'] for r in kernel_rect_data],
            'kernel_value': [r['kernel_value'] for r in kernel_rect_data],
        })

    # Base piano roll figure
    p = draw_piano_roll(
        df_notes,
        measure_offsets=measure_offsets,
        backend="bokeh",
        show=False,
        show_measure_lines=True,
        plot_width=plot_width,
        plot_height=plot_height,
        dpi=dpi,
        zoom_drag_dim=zoom_drag_dim,
        zoom_wheel_dim=zoom_wheel_dim,
    )

    rect_renderer = p.rect(
        x="x_center",
        y="y_center",
        width="width",
        height="height",
        source=overlay_source,
        fill_color="color",
        fill_alpha=float(fill_alpha),
        line_color="color",
        line_width=2,
    )

    # Add kernel visualization if requested
    kernel_renderer = None
    if kernel_source is not None:
        kernel_renderer = p.rect(
            x="x",
            y="y",
            width="width",
            height="height",
            source=kernel_source,
            fill_color=kernel_color,
            fill_alpha=float(kernel_alpha),
            line_color=kernel_color,
            line_width=1,
        )

    # Set up hover tool for both match rectangles and kernel rectangles
    hover_renderers = [rect_renderer]
    if kernel_renderer is not None:
        hover_renderers.append(kernel_renderer)

    hover = HoverTool(
        renderers=hover_renderers,
        tooltips=[
            ("Rank", "@rank"),
            ("Normalized overlap", "@score_norm{0.000}"),
            ("Raw overlap", "@score_raw{0.000}"),
            ("Time", "@time_start{0.00} - @time_end{0.00}"),
            ("Pitch span", "@midi_low - @midi_high"),
            ("Matrix indices", "(row=@row_idx, col=@col_idx)"),
        ],
    )
    p.add_tools(hover)

    # Axis labels and ranges
    p.yaxis.axis_label = "Pitch (MIDI)"

    y_min_overlay = min(rec["midi_low"] for rec in match_records) - 1.0
    y_max_overlay = max(rec["midi_high"] for rec in match_records) + 1.0
    p.y_range.start = min(p.y_range.start, y_min_overlay)
    p.y_range.end = max(p.y_range.end, y_max_overlay)

    x_min_overlay = min(rec["time_start"] for rec in match_records)
    x_max_overlay = max(rec["time_end"] for rec in match_records)
    p.x_range.start = min(p.x_range.start, x_min_overlay)
    p.x_range.end = max(p.x_range.end, x_max_overlay)

    if show:
        bokeh_show(p)

    df_matches = pd.DataFrame(match_records)
    df_matches["norm_value"] = norm_values
    return p, df_matches


