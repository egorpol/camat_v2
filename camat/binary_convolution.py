"""Teaching helpers for binary convolution notebooks."""

from __future__ import annotations

import sys
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
    "EXAMPLE_PASSAGE_SHAPE",
    "EXAMPLE_PATTERNS",
    "resolve_example_pattern",
    "make_random_host",
    "choose_placements",
    "show_musical_overlap_example",
    "show_rhythmic_augmentation_example",
    "show_pitch_interval_example",
    "show_placement",
    "show_example_overview",
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

EXAMPLE_PASSAGE_SHAPE = (10, 18)

EXAMPLE_PATTERNS = {
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


def resolve_example_pattern(name: str) -> tuple[str, np.ndarray]:
    """Return ``(canonical_name, copy)`` for a named example pattern."""
    key = str(name).strip().lower()
    if key not in EXAMPLE_PATTERNS:
        known = " | ".join(EXAMPLE_PATTERNS)
        raise KeyError(f"Unknown PATTERN_NAME {name!r}. Choose from: {known}")
    return key, EXAMPLE_PATTERNS[key].copy()


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
    shape: tuple[int, int] = EXAMPLE_PASSAGE_SHAPE,
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
            print(
                f"FIXED_I, FIXED_J = ({i}, {j}) is not a top-left where the "
                "pattern fits inside the passage."
            )
            print(f"Fitting row starts: {sorted({p[0] for p in valid})}")
            print(f"Fitting col starts: {sorted({p[1] for p in valid})}")
            return []
        if M[i : i + r, j : j + c].sum() == 0:
            print("That fixed window is all zeros; try another (i, j) or a denser passage.")
        return [(i, j)]
    if mode == "planted":
        hits = [p for p in planted if p in valid]
        if hits:
            return hits[:n_show]
        scored = [(score_kernel_at(M, K, i, j)[3], i, j) for i, j in valid]
        scored.sort(reverse=True)
        best = scored[0][0]
        print("No hidden copy in this passage; showing the best-scoring placement(s).")
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


def _teaching_phrase_svg(notes, *, show_meter=False):
    """Render the short, contiguous note sequences used in the worked examples."""
    from fractions import Fraction

    import verovio

    total = sum(Fraction(str(length)) for _pitch, length in notes)
    meter_count, meter_unit = total.numerator, 4 * total.denominator
    notation_notes = "".join(
        f'<note pname="{pitch[0].lower()}" oct="{pitch[-1]}" dur="{int(4 / length)}"/>'
        for pitch, length in notes
    )
    visible = "" if show_meter else ' meter.visible="false"'
    mei = (
        '<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0">'
        '<meiHead><fileDesc><titleStmt><title>Musical teaching example</title>'
        '</titleStmt><pubStmt/></fileDesc></meiHead>'
        f'<music><body><mdiv><score><scoreDef meter.count="{meter_count}" '
        f'meter.unit="{meter_unit}"{visible}>'
        '<staffGrp><staffDef n="1" lines="5" clef.shape="G" clef.line="2"/>'
        '</staffGrp></scoreDef><section><measure n="1"><staff n="1"><layer n="1">'
        f'{notation_notes}</layer></staff></measure></section></score></mdiv></body></music></mei>'
    )
    toolkit = verovio.toolkit()
    toolkit.setInputFrom("mei")
    toolkit.setOptions({"scale": 45, "pageWidth": 1000, "adjustPageHeight": True,
                        "breaks": "none", "header": "none", "footer": "none"})
    if not toolkit.loadData(mei) or not toolkit.getPageCount():
        raise RuntimeError("Could not render the musical teaching example.")
    svg = toolkit.renderToSVG(1)
    # Keep notation readable in both SVG outputs and dark-themed HTML panels.
    svg = svg.replace('<svg ', '<svg style="background-color:#fff;color:#000" ', 1)
    root_end = svg.index(">", svg.index("<svg")) + 1
    background = '<rect width="100%" height="100%" fill="#fff" style="stroke:none"/>'
    return svg[:root_end] + background + svg[root_end:]


def show_musical_overlap_example():
    """Show a notated four-note phrase and three predictable overlap cases.

    One column is an eighth note (0.5 quarter-note units). The four note
    events occupy six cells, making the duration weighting explicit.
    """
    import pandas as pd
    from IPython.display import SVG, display

    from .music_utils import create_binary_matrix_bundle

    phrase = [("C4", 60, 0.0, 1.0, "4"), ("D4", 62, 1.0, 0.5, "8"),
              ("E4", 64, 1.5, 0.5, "8"), ("G4", 67, 2.0, 1.0, "4")]
    notes = pd.DataFrame(phrase, columns=["Pitch", "MIDI", "Global Onset", "Duration", "dur"])
    bundle = create_binary_matrix_bundle(
        notes, resolution_method="manual", manual_resolution=0.5,
        y_mode="minmax", midi_low=60, midi_high=67, row_order="high_to_low",
        include_provenance=False,
    )
    kernel = np.asarray(bundle.matrix, dtype=float)
    display(SVG(_teaching_phrase_svg([(pitch, length) for pitch, _midi, _onset, length, _dur in phrase],
                                    show_meter=True)))

    missing = kernel.copy()
    missing[67 - 64, 3] = 0  # Omit the E4 eighth note.
    accompanied = kernel.copy()
    accompanied[-1, 2:] = 1  # Hold C4 under D4, E4, and G4.
    windows = {"Exact copy": kernel.copy(), "Missing E4": missing,
               "Added lower part (C4)": accompanied}
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.5), layout="constrained")
    total = int(kernel.sum())
    for ax, (label, window) in zip(axes, [("Pattern: four notes", kernel), *windows.items()]):
        _window, _product, raw, score = score_kernel_at(window, kernel, 0, 0)
        ax.imshow(window, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1,
                  interpolation="nearest", extent=(0, 3, 59.5, 67.5))
        ax.set(xticks=np.arange(0, 3.1, 0.5), yticks=[60, 62, 64, 67],
               yticklabels=["C4", "D4", "E4", "G4"], xlabel="Time (quarter-note units)")
        ax.set_xticks(np.arange(0, 3.1, 0.5), minor=True)
        ax.set_yticks(np.arange(59.5, 68, 1), minor=True)
        ax.grid(which="minor", color="#aaaaaa", linewidth=0.5)
        ax.grid(which="major", axis="x", color="#aaaaaa", linewidth=0.5)
        ax.tick_params(which="minor", length=0)
        extra = int(((window == 1) & (kernel == 0)).sum())
        ax.set_title(f"{label}\n{int(raw)}/{total} shared cells = {score:.2f}; extra={extra}")
    axes[0].set_ylabel("Pitch (one row = one semitone)")
    fig.suptitle("One cell = one eighth note at one pitch · black = active, white = inactive")
    plt.show()
    print("Four note events occupy six cells: each quarter note fills two cells.")
    print("Removing E4 leaves 5/6 = 0.833 of the occupied cells; the score is not the fraction of note events.")
    print("Adding the lower part keeps the score at 1.0: all six requested cells are still present.")
    return kernel, windows


def show_rhythmic_augmentation_example():
    """Compare diminution, the original phrase, and augmentation at fixed pitches.

    The sixteenth-note grid represents every halved duration exactly. Returns
    the three kernels, all with the same pitch rows and quarter-note resolution.
    """
    from IPython.display import HTML, display

    # C4 quarter, D4 eighth, E4 eighth, G4 quarter, at 0.25 QL per column.
    original = np.zeros((8, 12))
    for row, start, end in ((7, 0, 4), (5, 4, 6), (3, 6, 8), (0, 8, 12)):
        original[row, start:end] = 1
    factors = [0.5, 1.0, 2.0]
    labels = ["Time ×0.5: diminution", "Time ×1: original", "Time ×2: augmentation"]
    phrase = list(zip(("C4", "D4", "E4", "G4"), (1.0, 0.5, 0.5, 1.0)))
    kernels = {
        factor: resize_kernel(original, 1, factor, pitch_mode="fixed", time_mode="events")
        for factor in factors
    }
    notation = "".join(
        '<div style="flex:1;min-width:0"><p><strong>' + label + '</strong></p>'
        + _teaching_phrase_svg([(pitch, length * factor) for pitch, length in phrase]) + '</div>'
        for factor, label in zip(factors, labels)
    )
    display(HTML('<div style="display:flex;gap:1rem;flex-wrap:wrap;'
                 'background:#fff;color:#000;padding:0.5rem">' + notation + '</div>'))
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), layout="constrained")
    duration_names = ["eighth / sixteenth / sixteenth / eighth",
                      "quarter / eighth / eighth / quarter",
                      "half / quarter / quarter / half"]
    for ax, factor, label, names in zip(axes, factors, labels, duration_names):
        kernel = kernels[factor]
        end = kernel.shape[1] * 0.25
        ax.imshow(kernel, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1,
                  interpolation="nearest", extent=(0, end, 59.5, 67.5))
        ax.set(xlim=(0, 6), ylim=(59.5, 67.5), xticks=range(7),
               yticks=[60, 62, 64, 67], yticklabels=["C4", "D4", "E4", "G4"],
               xlabel="Time (quarter-note units)", title=f"{label}\nDuration: {end:g} quarter-note units")
        ax.set_xticks(np.arange(0, 6.1, 0.25), minor=True)
        ax.set_yticks(np.arange(59.5, 68, 1), minor=True)
        ax.grid(which="minor", color="#bbbbbb", linewidth=0.4)
        ax.grid(which="major", axis="x", color="#bbbbbb", linewidth=0.4)
        ax.tick_params(which="minor", length=0)
        ax.axvline(end, color="#666666", linestyle="--", linewidth=1)
        ax.text(0.5, -0.23, names, transform=ax.transAxes, ha="center", fontsize=9)
    axes[0].set_ylabel("Pitch (unchanged in all three versions)")
    fig.suptitle("Same pitches and cell size · one column = one sixteenth note (0.25 quarter-note units)")
    plt.show()
    return kernels


def show_pitch_interval_example():
    """Double D5–A4's five-semitone distance while keeping D5 and timing fixed."""
    from IPython.display import HTML, display

    original = np.zeros((6, 8))
    original[0, :4] = 1  # D5 (MIDI 74), one quarter note.
    original[5, 4:] = 1  # A4 (MIDI 69), one quarter note.
    doubled = resize_kernel(original, 2, 1, pitch_mode="intervals", time_mode="events")
    panels = [("Original: D5 → A4", original, "A4", 5),
              ("Pitch intervals ×2: D5 → E4", doubled, "E4", 10)]
    notation = "".join(
        '<div style="flex:1;min-width:0"><p><strong>' + label + '</strong></p>'
        + _teaching_phrase_svg([("D5", 1.0), (lower_pitch, 1.0)]) + '</div>'
        for label, _kernel, lower_pitch, _distance in panels
    )
    display(HTML('<div style="display:flex;gap:1rem;flex-wrap:wrap;'
                 'background:#fff;color:#000;padding:0.5rem">' + notation + '</div>'))
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.8), layout="constrained")
    for ax, (label, kernel, _lower_pitch, distance) in zip(axes, panels):
        ax.imshow(kernel, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1,
                  interpolation="nearest", extent=(0, 2, 74 - kernel.shape[0] + 0.5, 74.5))
        ax.set(xlim=(0, 2), ylim=(63.5, 74.5), xticks=[0, 1, 2],
               yticks=[64, 69, 74], yticklabels=["E4", "A4", "D5 (anchor)"],
               xlabel="Time (quarter-note units)", title=f"{label}\nDistance below D5: {distance} semitones")
        ax.set_xticks(np.arange(0, 2.1, 0.25), minor=True)
        ax.set_yticks(np.arange(63.5, 75, 1), minor=True)
        ax.grid(which="minor", color="#bbbbbb", linewidth=0.4)
        ax.grid(which="major", axis="x", color="#bbbbbb", linewidth=0.4)
        ax.tick_params(which="minor", length=0)
    axes[0].set_ylabel("Pitch (one row = one semitone)")
    fig.suptitle("D5 stays fixed · both notes still last one quarter note · each note stays one pitch row thick")
    plt.show()
    return original, doubled


def show_placement(M, K, i, j, title=None):
    """Draw host, window, kernel, and product for one placement."""
    window, product, raw, norm = score_kernel_at(M, K, i, j, normalize=True)
    fig, axes = plt.subplots(1, 4, figsize=(11, 2.8), constrained_layout=True)
    panels = [
        (M, "Passage + selected window", True),
        (window, "Passage window", False),
        (K, "Pattern", False),
        (product, "Shared occupied cells", False),
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


def show_example_overview(M, K, mark=None):
    """Draw the example passage, pattern, and fully-inside overlap heatmap."""
    scores, rows, cols, _ = convolution_map(M, K, padding="valid")
    fig, axes = plt.subplots(1, 3, figsize=(12.0, 3.4), constrained_layout=True)
    axes[0].imshow(M, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0].set_title(f"Example passage {M.shape}")
    axes[0].set_xlabel("time col")
    axes[0].set_ylabel("pitch row")
    axes[1].imshow(K, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[1].set_title(f"Example pattern {K.shape}")
    im = axes[2].imshow(scores, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[2].set_title("Overlap heatmap\n(one score per pattern position)")
    axes[2].set_xlabel("pattern top-left col $j$")
    axes[2].set_ylabel("pattern top-left row $i$")
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
    k_ones = int(K.sum())
    print(
        f"Overlap heatmap {scores.shape}: one normalised score for each pattern "
        f"position that fits inside the passage ({M.shape[0]}×{M.shape[1]}). "
        "White dots = the selected positions below."
    )
    print(
        f"Max raw overlap at one placement ≤ occupied pattern cells ({k_ones}) "
        "and ≤ occupied window cells; "
        "normalised overlap is therefore in [0, 1]."
    )
    if np.isfinite(scores).any():
        bi, bj = np.unravel_index(np.nanargmax(scores), scores.shape)
        print(
            f"Best normalised overlap: {scores[bi, bj]:.3f} "
            f"at top-left (i={rows[bi]}, j={cols[bj]})"
        )
    return scores


def show_host_and_kernel(host, kernel, *, host_title="Passage", kernel_title="Pattern"):
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
    """Compare fully-inside and edge-allowing placements on one passage."""
    scores_v, _, _, _ = convolution_map(M, K, padding="valid")
    scores_s, _, _, meta_s = convolution_map(M, K, padding="same")
    Mp, pad_y, pad_x = pad_for_same(M, K)

    fig, axes = plt.subplots(2, 2, figsize=(11.2, 6.6), constrained_layout=True)
    axes[0, 0].imshow(M, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0, 0].set_title(f"Passage {M.shape}\nwindows that fit inside")
    for i, j in placements:
        axes[0, 0].add_patch(_kernel_box(i, j, K, **_BOX_BLUE))
    axes[0, 1].imshow(Mp, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0, 1].set_title(
        f"Zero-padded {Mp.shape}\n"
        f"outside treated as empty ({pad_y} rows, {pad_x} cols)"
    )
    axes[0, 1].add_patch(
        Rectangle((pad_x - 0.5, pad_y - 0.5), M.shape[1], M.shape[0], **_BOX_GREY)
    )
    for i, j in placements:
        axes[0, 1].add_patch(_kernel_box(i + pad_y, j + pad_x, K, **_BOX_BLUE))
    axes[0, 1].add_patch(_kernel_box(0, 0, K, **_BOX_RED))
    im_v = axes[1, 0].imshow(
        scores_v, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1
    )
    axes[1, 0].set_title(f"Fully inside (valid)\n{scores_v.shape}")
    axes[1, 0].set_xlabel("pattern top-left col")
    axes[1, 0].set_ylabel("pattern top-left row")
    im_s = axes[1, 1].imshow(
        scores_s, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1,
        extent=(-pad_x - 0.5, M.shape[1] - pad_x - 0.5,
                M.shape[0] - pad_y - 0.5, -pad_y - 0.5),
    )
    axes[1, 1].set_title(f"Edges allowed (same)\n{scores_s.shape}")
    axes[1, 1].set_xlabel("pattern top-left col")
    axes[1, 1].set_ylabel("pattern top-left row")
    fig.colorbar(im_v, ax=axes[1, 0], shrink=0.85, pad=0.04)
    fig.colorbar(im_s, ax=axes[1, 1], shrink=0.85, pad=0.04)
    fig.suptitle(
        "Dashed grey = the passage on the wider grid; "
        "blue = the same interior windows; "
        "red dashed = the pattern hanging off the top-left into artificial empty cells"
    )
    plt.show()
    H, W = M.shape
    h, w = K.shape
    print(
        f"Fully inside (padding='valid'): map {scores_v.shape} = "
        f"({H}-{h}+1)×({W}-{w}+1) = {scores_v.size} placements, "
        f"best={np.nanmax(scores_v):.3f}."
    )
    print(
        f"Edges allowed (padding='same'): map {scores_s.shape} = "
        f"{H}×{W} = {scores_s.size} placements, "
        f"best={np.nanmax(scores_s):.3f}. "
        f"The wider grid is {meta_s['padded_shape']}. "
        "The border is artificial zero-padding; cells outside this excerpt are treated as empty."
    )
    return Mp, pad_y, pad_x


def show_valid_vs_same_window(M, K, i, j):
    """Show that adding an empty border leaves an interior window unchanged."""
    Mp, pad_y, pad_x = pad_for_same(M, K)
    i_s, j_s = i + pad_y, j + pad_x
    w_v, p_v, raw_v, n_v = score_kernel_at(M, K, i, j)
    w_s, p_s, raw_s, n_s = score_kernel_at(Mp, K, i_s, j_s)
    fig, axes = plt.subplots(2, 3, figsize=(9.4, 4.6), constrained_layout=True)
    panels = [
        (axes[0, 0], M, True, i, j, "Fits inside: passage + window"),
        (axes[0, 1], w_v, False, None, None, "Window"),
        (axes[0, 2], p_v, False, None, None, "Shared occupied cells"),
        (axes[1, 0], Mp, True, i_s, j_s, "Edges allowed: empty border + window"),
        (axes[1, 1], w_s, False, None, None, "Window (unchanged)"),
        (axes[1, 2], p_s, False, None, None, "Shared cells (unchanged)"),
    ]
    for ax, data, draw_box, bi, bj, label in panels:
        ax.imshow(data, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
        ax.set_title(label)
        if draw_box:
            ax.add_patch(_kernel_box(bi, bj, K, **_BOX_BLUE))
    fig.suptitle(
        f"Interior window, both policies  "
        f"fits inside (i={i}, j={j}) raw={raw_v:.0f} norm={n_v:.3f}  |  "
        f"edges allowed (i={i_s}, j={j_s}) raw={raw_s:.0f} norm={n_s:.3f}"
    )
    plt.show()
    same = np.array_equal(w_v, w_s) and abs(n_v - n_s) < 1e-12
    print(
        f"(i={i}, j={j}) lines up with the wider grid at (i={i_s}, j={j_s}): "
        f"windows identical={same}, fully inside={n_v:.3f}, edges allowed={n_s:.3f}"
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
    policy = "fully inside" if padding == "valid" else "edges allowed"
    if max_frames is not None and n_all > int(max_frames):
        idx = np.linspace(0, n_all - 1, int(max_frames)).astype(int)
        placements = [placements[k] for k in idx]
        print(
            f"{policy} ({padding}): subsampled animation {len(placements)}/{n_all} placements "
            f"(max_frames={int(max_frames)}). Set that cap to None to see every top-left."
        )
    else:
        print(
            f"{policy} ({padding}): {n_all} frames, one per placement "
            f"(stride=({stride_y},{stride_x}))."
        )

    if padding == "same":
        display_M, pad_y, pad_x = pad_for_same(M, K)
        host_title = f"Edges allowed: artificial empty border {display_M.shape}"
    else:
        display_M, pad_y, pad_x = M, 0, 0
        host_title = f"Fully inside: passage {M.shape} + sliding pattern"

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
    ax_s.set_title("Overlap heatmap (filling in)")
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


def _animation_frame_count(anim) -> int | None:
    """Return the known frame count for ``anim.save``.

    Matplotlib 3.8+ stores this as ``_save_count``. Older releases used the
    public ``save_count`` attribute. Either may be ``None`` when the length
    cannot be inferred.
    """
    for name in ("_save_count", "save_count"):
        value = getattr(anim, name, None)
        if value is not None:
            return int(value)
    return None


def _stdout_tqdm(total, desc, unit="frame"):
    """Text bar that JupyterLab still streams while Matplotlib is blocking.

    ``tqdm.notebook`` needs an ipywidgets frontend. Jupyter4NFDI often shows
    only the frozen text repr (``0frame [00:00, ?frame/s]``) and never paints
    the widget during ``anim.save``. A stdout bar with ``disable=False`` stays
    visible there. Pass a known ``total`` so the rate is not ``?frame/s``.
    """
    from tqdm import tqdm

    return tqdm(
        total=total,
        desc=desc,
        unit=unit,
        file=sys.stdout,
        ncols=88,
        mininterval=0.3,
        disable=False,
        leave=True,
    )


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
    When ``progress`` is true, a text ``tqdm`` bar on stdout tracks Matplotlib's
    frame encoding. Notebook widgets are not used: they do not update on
    Jupyter4NFDI during this blocking save.
    """
    from IPython.display import HTML, display

    fps = max(1.0, 1000.0 / float(interval_ms))
    writer = animation.HTMLWriter(fps=fps, embed_frames=True, default_mode="once")
    writer.frame_format = "jpeg"
    n_frames = _animation_frame_count(anim)
    pbar = _stdout_tqdm(n_frames, desc=desc) if progress else None

    def progress_callback(current_frame, total_frames):
        if pbar is None:
            return
        if total_frames is not None and pbar.total != total_frames:
            pbar.reset(total=total_frames)
        target = int(current_frame) + 1
        delta = target - pbar.n
        if delta:
            pbar.update(delta)
            sys.stdout.flush()

    def close_pbar():
        nonlocal pbar
        if pbar is None:
            return
        if pbar.total is not None and pbar.n < pbar.total:
            pbar.update(pbar.total - pbar.n)
        pbar.close()
        pbar = None

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
            # Finish the stdout bar before the HTML player. Jupyter treats
            # display() as a new output, so closing afterwards reprinted the
            # completed bar under Once / Loop / Reflect.
            close_pbar()
            display(HTML(Path(path).read_text()))
    finally:
        close_pbar()


def plot_stride_comparison(
    M,
    K,
    strides: Sequence[tuple[int, int]],
    *,
    resolution: float | None = None,
):
    """Side-by-side valid-padding score maps at different strides.

    When ``resolution`` is the host column width in quarter lengths, prints
    also map ``stride_x`` / ``stride_y`` to candidate start-time and pitch spacing.
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
        ax.set_xlabel("candidate start column on passage")
        ax.set_ylabel("candidate top-left pitch row")
        col_ticks = np.arange(0, len(cols), max(1, len(cols) // 5))
        row_ticks = np.arange(0, len(rows), max(1, len(rows) // 5))
        ax.set_xticks(col_ticks, [cols[index] for index in col_ticks])
        ax.set_yticks(row_ticks, [rows[index] for index in row_ticks])
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
    fig.suptitle("One Bach motif, different strides")
    plt.show()


def plot_padding_comparison(M, K):
    """Passage, pattern, and fully-inside vs edge-allowing score maps."""
    fig, axes = plt.subplots(1, 4, figsize=(14.5, 3.6), constrained_layout=True)
    axes[0].imshow(M, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[0].set_title(f"Passage {M.shape}")
    axes[0].set_xlabel("time col")
    axes[0].set_ylabel("pitch row")
    axes[1].imshow(K, cmap="Greys", origin="upper", aspect="auto", vmin=0, vmax=1)
    axes[1].set_title(f"Pattern {K.shape}")
    axes[1].set_xlabel("pattern col")
    axes[1].set_ylabel("pattern row")

    im = None
    labels = {"valid": "Fully inside (valid)", "same": "Edges allowed (same)"}
    for ax, mode in zip(axes[2:], ["valid", "same"]):
        scores, _, _, meta = convolution_map(
            M, K, stride_y=1, stride_x=1, normalize=True, padding=mode
        )
        im = ax.imshow(scores, cmap="viridis", origin="upper", aspect="auto", vmin=0, vmax=1)
        if mode == "same":
            im.set_extent((-meta["pad_x"] - 0.5, scores.shape[1] - meta["pad_x"] - 0.5,
                           scores.shape[0] - meta["pad_y"] - 0.5, -meta["pad_y"] - 0.5))
        ax.set_title(f"{labels[mode]}\nmap {scores.shape}")
        print(
            f"{labels[mode]}: score map {scores.shape}, "
            f"placements={scores.size}, best={np.nanmax(scores):.3f}, "
            f"empty border=({meta['pad_y']} rows, {meta['pad_x']} cols)"
        )
    if im is not None:
        fig.colorbar(im, ax=list(axes[2:]), shrink=0.85, pad=0.04)
    fig.suptitle("The edge policy changes which border placements exist")
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
    print("Passage unchanged: these scores test whether each transformed pattern occurs here.")
    im = None
    map_axes = []
    for a_i, axis in enumerate(axis_list):
        ax_k_row = axs[2 * a_i]
        ax_m_row = axs[2 * a_i + 1]
        ax_k_row[0].set_ylabel(f"pattern\n{axis_label[axis]}")
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
                ax_m.set_title("too large for the passage")
                ax_m.axis("off")
                print(
                    f"{axis} ×{factor:g}: {K.shape} → {Ks.shape} "
                    f"pattern does not fit the passage {M.shape}"
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
        "Scaled patterns searched on the unchanged passage"
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
