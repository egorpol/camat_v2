"""Teaching helpers for binary convolution notebooks."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
from matplotlib import animation, pyplot as plt
from matplotlib.patches import Rectangle

from .pattern_search import (
    convolution_map,
    kernel_placement_starts,
    pad_for_same,
    resize_kernel,
    score_kernel_at,
)

__all__ = [
    "TOY_HOST_SHAPE",
    "TOY_KERNELS",
    "resolve_toy_kernel",
    "make_random_host",
    "choose_placements",
    "show_placement",
    "show_toy_overview",
    "show_host_and_kernel",
    "show_padding_maps",
    "show_valid_vs_same_window",
    "animate_sliding_window",
    "display_anim_html",
    "plot_stride_comparison",
    "plot_padding_comparison",
    "plot_kernel_scales",
    "plot_kernel_augmentations",
    "filmstrip_placements",
    "binary_score_details",
    "plot_binary_score_explanation",
]


def binary_score_details(kernel: np.ndarray, window: np.ndarray) -> dict:
    """Explain the three search metrics cell by cell for binary arrays.

    ``cross_covariance`` is CAMAT's sum of centered products, without division
    by the cell count. A constant array has zero variance; normalized cross
    correlation is reported as zero, matching the search implementation.
    """
    import pandas as pd

    kernel, window = np.asarray(kernel, dtype=float), np.asarray(window, dtype=float)
    if kernel.ndim != 2 or not kernel.size or window.shape != kernel.shape:
        raise ValueError("Provide nonempty, equally shaped 2D kernel and window arrays.")
    if not np.isin(kernel, [0, 1]).all() or not np.isin(window, [0, 1]).all() or not kernel.any():
        raise ValueError("Use binary arrays and a kernel with at least one active cell.")
    k0, w0 = kernel - kernel.mean(), window - window.mean()
    product = kernel * window
    kind = np.full(kernel.shape, "silent in both", dtype=object)
    kind[(kernel == 1) & (window == 1)] = "shared"
    kind[(kernel == 1) & (window == 0)] = "missing"
    kind[(kernel == 0) & (window == 1)] = "extra"
    norm_k, norm_w = float(np.linalg.norm(k0)), float(np.linalg.norm(w0))
    covariance = float((k0 * w0).sum())
    rows, cols = np.indices(kernel.shape)
    return {
        "cells": pd.DataFrame({
            "row": rows.ravel(), "col": cols.ravel(), "K": kernel.ravel().astype(int),
            "W": window.ravel().astype(int), "K × W": product.ravel().astype(int),
            "kind": kind.ravel(), "K - mean(K)": k0.ravel(), "W - mean(W)": w0.ravel(),
            "centered product": (k0 * w0).ravel(),
        }),
        "n_cells": kernel.size, "kernel_active": int(kernel.sum()), "window_active": int(window.sum()),
        "shared": int(product.sum()), "missing": int(np.count_nonzero(kind == "missing")),
        "extra": int(np.count_nonzero(kind == "extra")), "silent_both": int(np.count_nonzero(kind == "silent in both")),
        "kernel_mean": float(kernel.mean()), "window_mean": float(window.mean()),
        "kernel_norm": norm_k, "window_norm": norm_w,
        "normalized_overlap": float(product.sum() / kernel.sum()),
        "cross_covariance": covariance,
        "normalized_cross_correlation": covariance / (norm_k * norm_w) if norm_k * norm_w > 0 else 0.0,
    }


def plot_binary_score_explanation(kernel: np.ndarray, windows: Mapping[str, np.ndarray]):
    """Show K, W, their product, and shared/missing/extra cells for each case.

    Coordinates are raw array indices so every plotted cell can be checked
    against ``binary_score_details()['cells']``. Intended for small examples.
    """
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    if not windows:
        raise ValueError("Provide at least one window to explain.")
    palette = ["#f4f4f4", "#cf268c", "#e76f18", "#c82b35"]
    fig, axes = plt.subplots(len(windows), 4, figsize=(12, 2.7 * len(windows)),
                             squeeze=False, layout="constrained")
    for axes_row, (label, window) in zip(axes, windows.items()):
        details = binary_score_details(kernel, window)
        k, w = np.asarray(kernel), np.asarray(window)
        categories = np.zeros(k.shape, dtype=int)
        categories[(k == 1) & (w == 1)] = 1
        categories[(k == 0) & (w == 1)] = 2
        categories[(k == 1) & (w == 0)] = 3
        panels = [(k, "Query K"), (w, f"{label}: W"), (k*w, f"K × W: sum = {details['shared']}"),
                  (categories, "Shared / extra / missing")]
        for index, (ax, (values, title)) in enumerate(zip(axes_row, panels)):
            ax.imshow(values, cmap=ListedColormap(palette) if index == 3 else "Greys",
                      vmin=0, vmax=3 if index == 3 else 1, interpolation="nearest", aspect="equal")
            for row, col in np.ndindex(k.shape):
                text = ["0/0", "1/1", "0/1", "1/0"][values[row, col]] if index == 3 else str(int(values[row, col]))
                ax.text(col, row, text, ha="center", va="center", fontsize=10,
                        color="white" if values[row, col] else "#333333")
            ax.set(title=title, xlabel="Column", ylabel="Raw row",
                   xticks=range(k.shape[1]), yticks=range(k.shape[0]))
            ax.set_xticks(np.arange(k.shape[1] + 1) - 0.5, minor=True)
            ax.set_yticks(np.arange(k.shape[0] + 1) - 0.5, minor=True)
            ax.grid(which="minor", color="#aaaaaa", linewidth=0.5)
            ax.tick_params(which="minor", length=0)
    fig.legend(handles=[Patch(facecolor=color, label=name) for color, name in zip(
        palette, ["Silent in both", "Shared: K=1, W=1", "Extra: K=0, W=1", "Missing: K=1, W=0"])],
        loc="outside lower center", ncols=4, frameon=False)
    return fig

TOY_HOST_SHAPE = (10, 18)

TOY_KERNELS = {
    "hold": np.array([[1, 1, 1]], dtype=float),
    "chord": np.array([[1], [1], [1]], dtype=float),
    "step_down": np.array([[1, 1, 0], [0, 0, 1]], dtype=float),
    "step_up": np.array([[0, 0, 1], [1, 1, 0]], dtype=float),
    "scale": np.array(
        [
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ],
        dtype=float,
    ),
    "leap": np.array(
        [
            [1, 0],
            [0, 0],
            [0, 1],
        ],
        dtype=float,
    ),
    "block": np.array([[1, 1], [1, 1]], dtype=float),
    "motif": np.array(
        [
            [1, 1, 0, 0, 0, 0],
            [0, 0, 1, 1, 0, 0],
            [0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 1],
        ],
        dtype=float,
    ),
    "thirds": np.array(
        [
            [1, 1, 0, 1, 1, 0],
            [0, 0, 0, 0, 0, 0],
            [1, 1, 0, 1, 1, 0],
        ],
        dtype=float,
    ),
    "turn": np.array(
        [
            [0, 1, 0, 0],
            [1, 0, 1, 1],
            [0, 0, 0, 0],
            [0, 0, 0, 1],
        ],
        dtype=float,
    ),
    "cadence": np.array(
        [
            [1, 0, 1],
            [1, 0, 0],
            [1, 0, 1],
            [0, 0, 1],
        ],
        dtype=float,
    ),
    "texture": np.array(
        [
            [1, 0, 1, 1, 0],
            [1, 1, 0, 1, 0],
            [0, 1, 1, 0, 1],
            [1, 0, 0, 1, 1],
        ],
        dtype=float,
    ),
}

_BOX_BLUE = dict(fill=False, edgecolor="#4e8bed", linewidth=2)
_BOX_GREY = dict(fill=False, edgecolor="#888888", linewidth=1.5, linestyle="--")
_BOX_RED = dict(fill=False, edgecolor="#d62728", linewidth=2, linestyle="--")


def resolve_toy_kernel(name: str) -> tuple[str, np.ndarray]:
    """Return ``(canonical_name, copy)`` for a named toy kernel."""
    key = str(name).strip().lower()
    if key not in TOY_KERNELS:
        known = " | ".join(TOY_KERNELS)
        raise KeyError(f"Unknown TOY_KERNEL_NAME {name!r}. Choose from: {known}")
    return key, TOY_KERNELS[key].copy()


def _stamp(M: np.ndarray, K: np.ndarray, i: int, j: int) -> np.ndarray:
    r, c = K.shape
    M[i : i + r, j : j + c] = np.maximum(M[i : i + r, j : j + c], K)
    return M


def _all_top_lefts(
    host_shape: tuple[int, int],
    kernel_shape: tuple[int, int],
    stride_y: int = 1,
    stride_x: int = 1,
) -> list[tuple[int, int]]:
    rows, cols = kernel_placement_starts(
        host_shape,
        kernel_shape,
        padding="valid",
        stride_y=stride_y,
        stride_x=stride_x,
    )
    return [(i, j) for i in rows for j in cols]


def _pick_top_left(host_shape, kernel_shape, rng) -> tuple[int, int]:
    opts = _all_top_lefts(host_shape, kernel_shape)
    if not opts:
        raise ValueError(f"Kernel {kernel_shape} does not fit host {host_shape}.")
    return opts[int(rng.integers(0, len(opts)))]


def _kernel_box(i, j, K, **style) -> Rectangle:
    return Rectangle((j - 0.5, i - 0.5), K.shape[1], K.shape[0], **style)


def make_random_host(
    density,
    kernel,
    rng,
    shape: tuple[int, int] = TOY_HOST_SHAPE,
    *,
    plant: bool = True,
):
    """Bernoulli host at ``density``, optionally with one planted kernel copy."""
    density = float(density)
    if not 0.0 <= density <= 1.0:
        raise ValueError(f"density must be in [0, 1], got {density}")
    M = (rng.random(shape) < density).astype(float)
    planted: list[tuple[int, int]] = []
    if plant:
        pos = _pick_top_left(shape, kernel.shape, rng)
        _stamp(M, kernel, *pos)
        planted = [pos]
    return M, planted


def choose_placements(M, K, mode, rng, n_show, planted, fixed):
    """Pick teaching windows: ``random``, ``planted``, or ``fixed``."""
    valid = _all_top_lefts(M.shape, K.shape)
    if not valid:
        return []
    mode = str(mode).strip().lower()
    n_show = max(1, int(n_show))
    r, c = K.shape
    if mode == "fixed":
        i, j = int(fixed[0]), int(fixed[1])
        if (i, j) not in valid:
            print(f"FIXED_I, FIXED_J = ({i}, {j}) is not a valid top-left.")
            print(f"Valid row starts: {sorted({p[0] for p in valid})}")
            print(f"Valid col starts: {sorted({p[1] for p in valid})}")
            return []
        if M[i : i + r, j : j + c].sum() == 0:
            print("That fixed window is all zeros; try another (i, j) or a denser host.")
        return [(i, j)]
    if mode == "planted":
        hits = [p for p in planted if p in valid]
        if hits:
            return hits[:n_show]
        scored = [(score_kernel_at(M, K, i, j)[3], i, j) for i, j in valid]
        scored.sort(reverse=True)
        best = scored[0][0]
        print("No planted copy on this host; showing the best-scoring placement(s).")
        return [(i, j) for nrm, i, j in scored if nrm == best][:n_show]
    nonempty = [(i, j) for i, j in valid if M[i : i + r, j : j + c].sum() > 0]
    pool = nonempty if nonempty else valid
    if nonempty and len(nonempty) < len(valid):
        print(
            f"Random mode: {len(nonempty)} windows contain at least one 1; "
            f"{len(valid) - len(nonempty)} empty windows skipped."
        )
    n = min(n_show, len(pool))
    pick = np.atleast_1d(rng.choice(len(pool), size=n, replace=False))
    return [pool[int(k)] for k in pick]


def show_placement(M, K, i, j, title=None):
    """Draw host, window, kernel, and product for one placement."""
    window, product, raw, norm = score_kernel_at(M, K, i, j, normalize=True)
    fig, axes = plt.subplots(1, 4, figsize=(11, 2.8), constrained_layout=True)
    panels = [
        (M, "Host + window", True),
        (window, "Window", False),
        (K, "Kernel", False),
        (product, "Product", False),
    ]
    for ax, (data, label, draw_box) in zip(axes, panels):
        ax.imshow(data, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
        ax.set_title(label)
        if draw_box:
            ax.add_patch(_kernel_box(i, j, K, **_BOX_BLUE))
    fig.suptitle(
        title or f"Placement (i={i}, j={j})  raw={raw:.0f}  normalised={norm:.3f}"
    )
    plt.show()
    return raw, norm


def show_toy_overview(M, K, mark=None):
    """Draw host, kernel, and the valid-padding overlap heatmap."""
    scores, rows, cols, _ = convolution_map(M, K, padding="valid")
    fig, axes = plt.subplots(1, 3, figsize=(12.0, 3.4), constrained_layout=True)
    axes[0].imshow(M, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0].set_title(f"Host {M.shape}")
    axes[0].set_xlabel("time col")
    axes[0].set_ylabel("pitch row")
    axes[1].imshow(K, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[1].set_title(f"Kernel {K.shape}")
    im = axes[2].imshow(scores, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[2].set_title("Overlap heatmap\n(one score per kernel position)")
    axes[2].set_xlabel("kernel top-left col $j$")
    axes[2].set_ylabel("kernel top-left row $i$")
    if mark:
        row_pos = {i: t for t, i in enumerate(rows)}
        col_pos = {j: t for t, j in enumerate(cols)}
        ys = [row_pos[i] for i, j in mark if i in row_pos and j in col_pos]
        xs = [col_pos[j] for i, j in mark if i in row_pos and j in col_pos]
        if ys:
            axes[2].scatter(
                xs,
                ys,
                s=40,
                c="white",
                edgecolors="black",
                zorder=3,
                label="selected kernel positions",
            )
            axes[2].legend(loc="upper left", fontsize=8, framealpha=0.9)
    fig.colorbar(im, ax=axes[2], shrink=0.85, pad=0.04)
    plt.show()
    H, W = M.shape
    h, w = K.shape
    n_valid = (H - h + 1) * (W - w + 1)
    n_same = H * W
    k_ones = int(K.sum())
    print(
        f"Overlap heatmap {scores.shape}: each cell is the normalised overlap "
        f"for one valid kernel top-left. White dots = the selected positions below."
    )
    print(
        f"Placements at stride 1: valid (H-h+1)×(W-w+1) = ({H}-{h}+1)×({W}-{w}+1) "
        f"= {n_valid}; same H×W = {H}×{W} = {n_same}."
    )
    print(
        f"Max raw overlap at one placement ≤ kernel 1s ({k_ones}) and ≤ window 1s; "
        f"normalised overlap is therefore in [0, 1]."
    )
    if np.isfinite(scores).any():
        bi, bj = np.unravel_index(np.nanargmax(scores), scores.shape)
        print(
            f"Best normalised overlap: {scores[bi, bj]:.3f} "
            f"at top-left (i={rows[bi]}, j={cols[bj]})"
        )
    return scores


def show_host_and_kernel(host, kernel, *, host_title="Host", kernel_title="Kernel"):
    """Side-by-side binary host and kernel."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), constrained_layout=True)
    axes[0].imshow(host, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0].set_title(host_title)
    axes[0].set_xlabel("time col")
    axes[0].set_ylabel("pitch row")
    axes[1].imshow(kernel, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[1].set_title(kernel_title)
    axes[1].set_xlabel("kernel col")
    axes[1].set_ylabel("kernel row")
    plt.show()


def show_padding_maps(M, K, placements):
    """Compare valid vs same padding on the same host, kernel, and windows."""
    scores_v, _, _, meta_v = convolution_map(M, K, padding="valid")
    scores_s, _, _, meta_s = convolution_map(M, K, padding="same")
    Mp, pad_y, pad_x = pad_for_same(M, K)

    fig, axes = plt.subplots(2, 2, figsize=(11.2, 6.6), constrained_layout=True)
    axes[0, 0].imshow(M, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0, 0].set_title(f"Host {M.shape} + valid windows")
    for i, j in placements:
        axes[0, 0].add_patch(_kernel_box(i, j, K, **_BOX_BLUE))
    axes[0, 1].imshow(Mp, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0, 1].set_title(f"Same-padded {Mp.shape}  pad=({pad_y},{pad_x})")
    axes[0, 1].add_patch(
        Rectangle((pad_x - 0.5, pad_y - 0.5), M.shape[1], M.shape[0], **_BOX_GREY)
    )
    for i, j in placements:
        axes[0, 1].add_patch(_kernel_box(i + pad_y, j + pad_x, K, **_BOX_BLUE))
    axes[0, 1].add_patch(_kernel_box(0, 0, K, **_BOX_RED))
    im_v = axes[1, 0].imshow(
        scores_v, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1
    )
    axes[1, 0].set_title(f"Valid overlap heatmap {scores_v.shape}")
    axes[1, 0].set_xlabel("kernel top-left col")
    axes[1, 0].set_ylabel("kernel top-left row")
    im_s = axes[1, 1].imshow(
        scores_s, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1
    )
    axes[1, 1].set_title(f"Same overlap heatmap {scores_s.shape}")
    axes[1, 1].set_xlabel("kernel top-left col")
    axes[1, 1].set_ylabel("kernel top-left row")
    fig.colorbar(im_v, ax=axes[1, 0], shrink=0.85, pad=0.04)
    fig.colorbar(im_s, ax=axes[1, 1], shrink=0.85, pad=0.04)
    fig.suptitle(
        "Dashed grey = original host on the padded canvas; "
        "blue = same interior windows; red dashed = a same-only edge window"
    )
    plt.show()
    print(
        f"valid: map {scores_v.shape}, {scores_v.size} placements, "
        f"best={np.nanmax(scores_v):.3f}  (run_pattern_search padding='valid')"
    )
    print(
        f"same:  map {scores_s.shape}, {scores_s.size} placements, "
        f"best={np.nanmax(scores_s):.3f}, padded host {meta_s['padded_shape']}  "
        f"(run_pattern_search padding='same')"
    )
    return Mp, pad_y, pad_x


def show_valid_vs_same_window(M, K, i, j):
    """Show that an interior window is identical under valid and same padding."""
    Mp, pad_y, pad_x = pad_for_same(M, K)
    i_s, j_s = i + pad_y, j + pad_x
    w_v, p_v, raw_v, n_v = score_kernel_at(M, K, i, j)
    w_s, p_s, raw_s, n_s = score_kernel_at(Mp, K, i_s, j_s)
    fig, axes = plt.subplots(2, 3, figsize=(9.4, 4.6), constrained_layout=True)
    panels = [
        (axes[0, 0], M, True, i, j, "Valid host + window"),
        (axes[0, 1], w_v, False, None, None, "Valid window"),
        (axes[0, 2], p_v, False, None, None, "Valid product"),
        (axes[1, 0], Mp, True, i_s, j_s, "Same-padded host + window"),
        (axes[1, 1], w_s, False, None, None, "Same window"),
        (axes[1, 2], p_s, False, None, None, "Same product"),
    ]
    for ax, data, draw_box, bi, bj, label in panels:
        ax.imshow(data, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
        ax.set_title(label)
        if draw_box:
            ax.add_patch(_kernel_box(bi, bj, K, **_BOX_BLUE))
    fig.suptitle(
        f"Same interior window  valid (i={i}, j={j}) raw={raw_v:.0f} norm={n_v:.3f}  |  "
        f"same (i={i_s}, j={j_s}) raw={raw_s:.0f} norm={n_s:.3f}"
    )
    plt.show()
    same = np.array_equal(w_v, w_s) and abs(n_v - n_s) < 1e-12
    print(
        f"(i={i}, j={j}) → padded (i={i_s}, j={j_s}): "
        f"windows identical={same}, valid={n_v:.3f}, same={n_s:.3f}"
    )
    return n_v, n_s


def animate_sliding_window(
    M,
    K,
    stride_y=1,
    stride_x=1,
    max_frames=None,
    interval_ms=180,
    padding="valid",
):
    """Animate the kernel walking across the host while the score map fills in."""
    scores, rows, cols, _meta = convolution_map(
        M, K, stride_y=stride_y, stride_x=stride_x, normalize=True, padding=padding
    )
    placements = [(i, j, ii, jj) for ii, i in enumerate(rows) for jj, j in enumerate(cols)]
    n_all = len(placements)
    if max_frames is not None and n_all > int(max_frames):
        idx = np.linspace(0, n_all - 1, int(max_frames)).astype(int)
        placements = [placements[k] for k in idx]
        print(
            f"{padding}: subsampled animation {len(placements)}/{n_all} placements "
            f"(max_frames={int(max_frames)}). Set that cap to None to see every top-left."
        )
    else:
        print(
            f"{padding}: {n_all} frames, one per placement "
            f"(stride=({stride_y},{stride_x}))."
        )

    if padding == "same":
        display_M, pad_y, pad_x = pad_for_same(M, K)
        host_title = f"Same-padded host {display_M.shape} + sliding kernel"
    else:
        display_M, pad_y, pad_x = M, 0, 0
        host_title = f"Host {M.shape} + sliding kernel (valid)"

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 3.8), constrained_layout=True)
    ax_m, ax_s = axes
    ax_m.imshow(display_M, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    if padding == "same":
        ax_m.add_patch(
            Rectangle((pad_x - 0.5, pad_y - 0.5), M.shape[1], M.shape[0], **_BOX_GREY)
        )
    rect = _kernel_box(0, 0, K, **_BOX_BLUE)
    ax_m.add_patch(rect)
    ax_m.set_title(host_title)
    ax_m.set_xlabel("time col")
    ax_m.set_ylabel("pitch row")

    score_img = np.full_like(scores, np.nan)
    im = ax_s.imshow(
        score_img,
        cmap="viridis",
        origin="upper",
        aspect="auto",
        vmin=0,
        vmax=1,
    )
    ax_s.set_title(f"{padding} overlap heatmap (filling in)")
    ax_s.set_xlabel("placement col index")
    ax_s.set_ylabel("placement row index")
    fig.colorbar(im, ax=ax_s, shrink=0.85, pad=0.04)

    def update(frame_idx):
        i, j, ii, jj = placements[frame_idx]
        rect.set_xy((j - 0.5, i - 0.5))
        score_img[ii, jj] = scores[ii, jj]
        im.set_data(score_img)
        if padding == "same":
            host_i, host_j = i - pad_y, j - pad_x
            ax_m.set_xlabel(
                f"time col  |  padded (i={i}, j={j})  host (i={host_i}, j={host_j})  "
                f"score={scores[ii, jj]:.2f}"
            )
        else:
            ax_m.set_xlabel(
                f"time col  |  host (i={i}, j={j})  score={scores[ii, jj]:.2f}"
            )
        return (rect, im)

    anim = animation.FuncAnimation(
        fig,
        update,
        frames=len(placements),
        interval=interval_ms,
        blit=False,
        repeat=False,
    )
    plt.close(fig)
    return anim, scores


def _notebook_tqdm(total, desc, unit="frame"):
    """Prefer ``tqdm.notebook`` in Jupyter; fall back to ``tqdm.auto``."""
    try:
        from tqdm.notebook import tqdm
    except ImportError:
        from tqdm.auto import tqdm
    return tqdm(total=total, desc=desc, unit=unit)


def display_anim_html(
    anim,
    interval_ms,
    dpi=100,
    jpeg_quality=85,
    *,
    progress=True,
    desc="Rendering frames",
):
    """Embed every frame as JPEG so a full same-padding walk fits in the notebook.

    ``dpi`` is pixels per inch of the figure (raise this if the movie looks
    blurry). ``jpeg_quality`` is 1–95 (raise this if you see blocky artifacts).
    When ``progress`` is true, a ``tqdm.notebook`` bar tracks Matplotlib's
    frame encoding (the slow part of building the HTML player).
    """
    from IPython.display import HTML, display

    fps = max(1.0, 1000.0 / float(interval_ms))
    writer = animation.HTMLWriter(fps=fps, embed_frames=True, default_mode="once")
    writer.frame_format = "jpeg"
    n_guess = getattr(anim, "save_count", None)
    pbar = _notebook_tqdm(n_guess, desc=desc) if progress else None

    def progress_callback(current_frame, total_frames):
        if pbar is None:
            return
        if total_frames is not None and pbar.total != total_frames:
            pbar.reset(total=total_frames)
        pbar.n = int(current_frame) + 1
        pbar.refresh()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "anim.html")
            anim.save(
                path,
                writer=writer,
                dpi=dpi,
                savefig_kwargs={
                    "facecolor": "white",
                    "pil_kwargs": {"quality": int(jpeg_quality)},
                },
                progress_callback=progress_callback if progress else None,
            )
            display(HTML(Path(path).read_text()))
    finally:
        if pbar is not None:
            pbar.close()


def plot_stride_comparison(
    M,
    K,
    strides: Sequence[tuple[int, int]],
    *,
    resolution: float | None = None,
):
    """Side-by-side valid-padding score maps at different strides.

    When ``resolution`` is the host column width in quarter lengths, prints
    also map ``stride_x`` / ``stride_y`` to duration and pitch intervals.
    """
    n = len(strides)
    fig, axes = plt.subplots(
        1, n, figsize=(3.2 * n + 0.8, 3.4), squeeze=False, constrained_layout=True
    )
    im = None
    for ax, (sy, sx) in zip(axes[0], strides):
        scores, rows, cols, _ = convolution_map(
            M, K, stride_y=sy, stride_x=sx, normalize=True, padding="valid"
        )
        im = ax.imshow(scores, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1)
        ax.set_title(f"stride=({sy},{sx})\nmap {scores.shape}")
        ax.set_xlabel("placement col")
        ax.set_ylabel("placement row")
        extra = ""
        if resolution is not None:
            extra = (
                f", start every {sy} semitone(s) / "
                f"{sx * float(resolution):g} QL"
            )
        print(
            f"stride=({sy},{sx}): placements={scores.size}, "
            f"best={np.nanmax(scores):.3f}, "
            f"row stops={rows[:6]}{'...' if len(rows) > 6 else []}{extra}"
        )
    if im is not None:
        fig.colorbar(im, ax=axes[0].tolist(), shrink=0.85, pad=0.04)
    fig.suptitle("Same Bach motif, different strides")
    plt.show()


def plot_padding_comparison(M, K):
    """Host, kernel, plus valid vs same score maps."""
    fig, axes = plt.subplots(1, 4, figsize=(14.5, 3.6), constrained_layout=True)
    axes[0].imshow(M, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0].set_title(f"Host {M.shape}")
    axes[0].set_xlabel("time col")
    axes[0].set_ylabel("pitch row")
    axes[1].imshow(K, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[1].set_title(f"Kernel {K.shape}")
    axes[1].set_xlabel("kernel col")
    axes[1].set_ylabel("kernel row")

    im = None
    for ax, mode in zip(axes[2:], ["valid", "same"]):
        scores, rows, cols, meta = convolution_map(
            M, K, stride_y=1, stride_x=1, normalize=True, padding=mode
        )
        im = ax.imshow(scores, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1)
        ax.set_title(
            f"{mode} map {scores.shape}\n"
            f"pad=({meta['pad_y']},{meta['pad_x']}) padded={meta['padded_shape']}"
        )
        print(
            f"{mode}: score map {scores.shape}, "
            f"placements={scores.size}, best={np.nanmax(scores):.3f}"
        )
    if im is not None:
        fig.colorbar(im, ax=list(axes[2:]), shrink=0.85, pad=0.04)
    fig.suptitle("Padding changes where edge placements exist")
    plt.show()


def plot_kernel_scales(
    M,
    K,
    scales: Iterable[float] = (0.5, 0.75, 1.0, 1.5, 2.0),
    scale_axes: Sequence[str] = ("x", "y", "both"),
    *,
    kernel_resize_method: str = "nearest",
    kernel_pitch_mode: str = "stretch",
    kernel_time_mode: str = "resample",
    kernel_rounding: str = "nearest",
    binarize_scaled_kernel: bool = True,
    binarize_threshold: float = 0.5,
):
    """Scaled kernels and valid-padding maps along time, pitch, or both.

    Each column is a scale factor; each pair of rows is one axis (kernel then
    score map). Factors below 1 shrink the kernel (diminution); above 1 stretch
    it (augmentation). This is the same ``resize_kernel`` path as
    ``run_pattern_search(..., kernel_scale_axes=..., kernel_scale_factors=...)``:
    all pitch/time/sampling/rounding and threshold options match the search API.
    Use ``kernel_pitch_mode="intervals", kernel_time_mode="events"`` to move
    each note to one pitch row and scale its time boundaries. Defaults retain
    geometric nearest-cell resizing. Titles print size and active cell count.
    The host stays unchanged: a lower score does not diagnose resize accuracy.
    """
    scales = [float(s) for s in scales]
    axis_list = [str(a).strip().lower() for a in scale_axes]
    for axis in axis_list:
        if axis not in {"x", "y", "both"}:
            raise ValueError(f"axis must be 'x', 'y', or 'both'; got {axis!r}")
    n_sc = len(scales)
    n_ax = len(axis_list)
    fig, axs = plt.subplots(
        2 * n_ax,
        n_sc,
        figsize=(2.8 * n_sc + 0.8, 2.15 * 2 * n_ax + 0.8),
        squeeze=False,
        constrained_layout=True,
    )
    axis_label = {"x": "time (x)", "y": "pitch (y)", "both": "pitch + time"}
    print(
        f"resize_kernel: pitch={kernel_pitch_mode}, time={kernel_time_mode}, "
        f"method={kernel_resize_method}, rounding={kernel_rounding}; "
        + (f"then ≥ {binarize_threshold:g}" if binarize_scaled_kernel else "keep weights")
    )
    print("Host unchanged: these scores test whether each transformed pattern occurs here.")
    im = None
    map_axes = []
    for a_i, axis in enumerate(axis_list):
        ax_k_row = axs[2 * a_i]
        ax_m_row = axs[2 * a_i + 1]
        ax_k_row[0].set_ylabel(f"kernel\n{axis_label[axis]}")
        ax_m_row[0].set_ylabel(f"map\n{axis_label[axis]}")
        for col, factor in enumerate(scales):
            scale_y = factor if axis in {"y", "both"} else 1.0
            scale_x = factor if axis in {"x", "both"} else 1.0
            Ks = resize_kernel(
                K, scale_y=scale_y, scale_x=scale_x, method=kernel_resize_method,
                pitch_mode=kernel_pitch_mode, time_mode=kernel_time_mode,
                rounding=kernel_rounding,
            )
            if binarize_scaled_kernel:
                Ks = (Ks >= binarize_threshold).astype(float)
            ax_k = ax_k_row[col]
            ax_m = ax_m_row[col]
            ax_k.imshow(
                Ks, cmap="Greys", origin="upper", aspect="equal",
                interpolation="nearest", vmin=0, vmax=1,
            )
            ax_k.set_title(
                f"{axis} ×{factor:g}\n{K.shape[0]}×{K.shape[1]}→{Ks.shape[0]}×{Ks.shape[1]}"
                f"; weight={Ks.sum():g}"
            )
            if Ks.shape[0] > M.shape[0] or Ks.shape[1] > M.shape[1]:
                ax_m.set_title("too large for host")
                ax_m.axis("off")
                print(
                    f"{axis} ×{factor:g}: {K.shape} → {Ks.shape} "
                    f"kernel does not fit host {M.shape}"
                )
                continue
            scores, _, _, _ = convolution_map(
                M, Ks, stride_y=1, stride_x=1, normalize=True, padding="valid"
            )
            im = ax_m.imshow(
                scores, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1
            )
            map_axes.append(ax_m)
            ax_m.set_title(f"map {scores.shape}\nbest={np.nanmax(scores):.2f}")
            print(
                f"{axis} ×{factor:g}: {K.shape} → {Ks.shape} "
                f"weight={Ks.sum():g}, map {scores.shape}, "
                f"best={np.nanmax(scores):.3f}"
            )
    if im is not None and map_axes:
        fig.colorbar(im, ax=map_axes, shrink=0.6, pad=0.02)
    fig.suptitle(
        f"Pitch: {kernel_pitch_mode}; time: {kernel_time_mode}; {kernel_resize_method}\n"
        "Scaled kernels searched on the unchanged host"
    )
    plt.show()


def plot_kernel_augmentations(
    K,
    variants: Mapping[str, Mapping[str, object]],
    *,
    scale_y: float = 1.5,
    scale_x: float = 1.5,
    binarize_scaled_kernel: bool = True,
    binarize_threshold: float = 0.5,
    ncols: int = 3,
):
    """Compare named augmentation recipes and return their actual kernels.

    Each recipe supplies keyword arguments for :func:`resize_kernel`, e.g.
    ``{"One-row notes": {"pitch_mode": "intervals", "time_mode": "events"}}``.
    Recipes can override the shared scale factors. Binarization matches search;
    disable it to inspect bilinear/area weights. All panels use the same cell
    size, with the original included as a reference. ``peak/col`` counts the
    maximum number of nonzero rows in a column; it exposes invented pitch bands
    or time blending without interpreting a polyphonic source as monophonic.
    """
    K = np.asarray(K, dtype=float)
    if not variants:
        raise ValueError("variants must contain at least one augmentation recipe.")
    kernels = {}
    for name, options in variants.items():
        kwargs = {"scale_y": scale_y, "scale_x": scale_x, **options}
        kernel = resize_kernel(K, **kwargs)
        if binarize_scaled_kernel:
            kernel = (kernel >= binarize_threshold).astype(float)
        kernels[name] = kernel
    panels = [("Original", K), *kernels.items()]
    ncols = min(len(panels), max(1, int(ncols)))
    nrows = int(np.ceil(len(panels) / ncols))
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(4.1 * ncols, 2.6 * nrows),
        squeeze=False, constrained_layout=True,
    )
    max_height = max(k.shape[0] for _, k in panels)
    max_width = max(k.shape[1] for _, k in panels)
    for ax, (label, kernel) in zip(axes.flat, panels):
        ax.imshow(
            kernel, cmap="Greys", origin="upper", aspect="equal",
            interpolation="nearest", vmin=0, vmax=1,
        )
        ax.set_xlim(-0.5, max_width - 0.5)
        ax.set_ylim(max_height - 0.5, -0.5)
        ax.add_patch(_kernel_box(0, 0, kernel, **_BOX_GREY))
        peak = int(np.count_nonzero(kernel, axis=0).max())
        ax.set_title(f"{label}\n{kernel.shape}; weight={kernel.sum():g}; peak/col={peak}")
        ax.set_xlabel("time column")
        ax.set_ylabel("pitch row")
    for ax in axes.flat[len(panels):]:
        ax.axis("off")
    fig.suptitle("Augmentation recipes · same cell size in every panel")
    plt.show()
    return kernels


def filmstrip_placements(M, K, placements, ncols=4, title="Selected sliding-window placements"):
    """Static frames of selected kernel placements on one host."""
    n = len(placements)
    nrows = int(np.ceil(n / ncols)) if n else 1
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(3.0 * ncols, 2.8 * nrows), constrained_layout=True
    )
    axes = np.atleast_2d(axes)
    for ax, (i, j) in zip(axes.ravel(), placements):
        ax.imshow(M, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
        _, _, raw, norm = score_kernel_at(M, K, i, j)
        ax.add_patch(_kernel_box(i, j, K, **_BOX_BLUE))
        ax.set_title(f"(i={i}, j={j})\nnorm={norm:.2f}")
        ax.set_xticks([])
        ax.set_yticks([])
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    fig.suptitle(title)
    plt.show()
