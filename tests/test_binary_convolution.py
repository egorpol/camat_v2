from __future__ import annotations

import numpy as np
import pytest

from camat.binary_convolution import (
    TOY_KERNELS,
    choose_placements,
    make_random_host,
    plot_kernel_augmentations,
    plot_kernel_scales,
    resolve_toy_kernel,
)


def test_resolve_toy_kernel_returns_copy() -> None:
    key, kernel = resolve_toy_kernel("motif")
    assert key == "motif"
    assert kernel.shape == TOY_KERNELS["motif"].shape
    kernel[0, 0] = 0
    assert TOY_KERNELS["motif"][0, 0] == 1.0


def test_make_random_host_plants_perfect_match() -> None:
    rng = np.random.default_rng(0)
    _, kernel = resolve_toy_kernel("motif")
    host, planted = make_random_host(0.0, kernel, rng, shape=(10, 18), plant=True)
    assert planted
    i, j = planted[0]
    r, c = kernel.shape
    assert np.array_equal(host[i : i + r, j : j + c], kernel)
    hits = choose_placements(host, kernel, "planted", rng, 1, planted, (0, 0))
    assert hits == planted[:1]


def test_make_random_host_density_bounds() -> None:
    rng = np.random.default_rng(1)
    _, kernel = resolve_toy_kernel("hold")
    with pytest.raises(ValueError, match="density"):
        make_random_host(1.2, kernel, rng)


@pytest.mark.parametrize("method", ["nearest", "bilinear", "area"])
def test_scale_plot_uses_selected_search_resize_method(monkeypatch, method) -> None:
    from matplotlib import pyplot as plt
    from camat.pattern_search import resize_kernel

    kernel = np.eye(3)
    host = kernel.repeat(2, axis=0).repeat(2, axis=1)
    monkeypatch.setattr(plt, "show", lambda: None)
    try:
        kwargs = {} if method == "nearest" else {"kernel_resize_method": method}
        plot_kernel_scales(host, kernel, scales=[2], scale_axes=["both"], **kwargs)
        image = plt.gcf().axes[0].images[0]
        expected = (resize_kernel(kernel, 2, 2, method=method) >= .5).astype(float)
        np.testing.assert_array_equal(image.get_array(), expected)
        assert image.get_interpolation() == "nearest"
    finally:
        plt.close("all")


def test_scale_plot_and_search_share_pitch_time_and_rounding_controls(monkeypatch):
    from matplotlib import pyplot as plt
    from camat.pattern_search import run_pattern_search

    kernel = np.eye(3)
    host = np.zeros((6, 8))
    expected = np.array([[1, 1, 0, 0, 0], [0, 0, 0, 0, 0],
                         [0, 0, 1, 0, 0], [0, 0, 0, 1, 1]])
    host[1:5, 2:7] = expected
    options = dict(kernel_pitch_mode="intervals", kernel_time_mode="events",
                   kernel_rounding="ceil", kernel_resize_method="area")
    monkeypatch.setattr(plt, "show", lambda: None)
    try:
        plot_kernel_scales(host, kernel, scales=[1.5], scale_axes=["both"], **options)
        np.testing.assert_array_equal(plt.gcf().axes[0].images[0].get_array(), expected)
        scores = plt.gcf().axes[1].images[0].get_array()
        results, _, key, _ = run_pattern_search(
            host, kernel, metrics_to_run=["normalized_overlap"],
            kernel_scale_factors=[1.5], kernel_scale_axes=["both"],
            backend="none", top_n_matches=0, **options,
        )
        np.testing.assert_array_equal(scores, results[key]["normalized_overlap"].to_numpy())
    finally:
        plt.close("all")


def test_notebook_tqdm_falls_back_when_ipywidgets_missing(monkeypatch):
    import sys

    import tqdm as tqdm_std

    import camat.binary_convolution as bc

    monkeypatch.setitem(sys.modules, "ipywidgets", None)
    pbar = bc._notebook_tqdm(10, "Encoding frames")
    try:
        assert type(pbar) is tqdm_std.tqdm
        assert pbar.total == 10
        pbar.update(3)
        assert pbar.n == 3
    finally:
        pbar.close()


def test_notebook_tqdm_falls_back_when_widget_construction_fails(monkeypatch):
    import sys
    import types

    import tqdm as tqdm_std

    import camat.binary_convolution as bc

    widgets = types.ModuleType("ipywidgets")
    widgets.IntProgress = object
    fake_notebook = types.ModuleType("tqdm.notebook")

    def boom(*args, **kwargs):
        raise ImportError("IProgress not found")

    fake_notebook.tqdm = boom
    monkeypatch.setitem(sys.modules, "ipywidgets", widgets)
    monkeypatch.setitem(sys.modules, "tqdm.notebook", fake_notebook)

    pbar = bc._notebook_tqdm(4, "Encoding frames")
    try:
        assert type(pbar) is tqdm_std.tqdm
        pbar.update(1)
        assert pbar.n == 1
    finally:
        pbar.close()


def test_recipe_comparison_returns_displayed_kernels_without_mutating_recipes(monkeypatch):
    from matplotlib import pyplot as plt

    recipes = {"Line": {"pitch_mode": "intervals", "time_mode": "events"},
               "Band": {"pitch_mode": "stretch", "scale_y": 3}}
    monkeypatch.setattr(plt, "show", lambda: None)
    try:
        kernels = plot_kernel_augmentations(np.eye(2), recipes, scale_y=2, scale_x=1)
        np.testing.assert_array_equal(kernels["Line"], [[1, 0], [0, 0], [0, 1]])
        np.testing.assert_array_equal(kernels["Band"], np.eye(2).repeat(3, axis=0))
        for ax, expected in zip(plt.gcf().axes[1:], kernels.values()):
            np.testing.assert_array_equal(ax.images[0].get_array(), expected)
        assert recipes["Line"] == {"pitch_mode": "intervals", "time_mode": "events"}
    finally:
        plt.close("all")
