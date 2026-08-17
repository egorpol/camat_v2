---
title: MEI facsimile viewer
---

# MEI facsimile viewer

`camat.facsimile_viewer` provides a reusable inspection layer for any local
MEI. It always renders the notation with Verovio. When the MEI includes usable
facsimile records, it also places measure zones over the image and links both
representations interactively.

## Two modes

| MEI content | Viewer result |
| --- | --- |
| No usable `<facsimile>` records | full-width score-only view |
| Graphic, measure zones, and matching measure `@facs` links | linked score and facsimile panes |

The notebook and interactive API default to score-only fallback. This means a
plain MEI is valid input, and the same open viewer can detect facsimile records
added later through **Check facsimile** or automatic file watching.

Use strict parsing when absence itself should fail editorial validation:

```python
from camat import FacsimileUnavailableError, read_facsimile_model

try:
    model = read_facsimile_model("page.mei")  # strict by default
except FacsimileUnavailableError as error:
    print(error)
```

`allow_missing_facsimile=True` only tolerates absent structural records. It
does not hide inconsistent data: invalid coordinates, missing identifiers, and
unresolved measure `@facs` links still raise errors.

## Linked-facsimile input

To enable the linked two-pane mode, the MEI needs:

- a `<facsimile>` with at least one `<surface>`;
- a `<graphic>` with `@target`, `@width`, and `@height` on the first surface;
- `<zone type="measure">` elements with coordinates and `xml:id` values;
- score measures whose `@facs` values point to those zone identifiers.

The current viewer is deliberately page-oriented and displays the **first
facsimile surface**. Verovio may produce several score SVG pages for that MEI
page, and the viewer supplies previous/next controls for them. Use one MEI
page—or select/extract the required surface before launch—for multi-surface
files.

## Local notebook use

```python
from camat import launch_interactive_facsimile_viewer

viewer = launch_interactive_facsimile_viewer(
    "/path/to/score.mei",  # facsimile records are optional
    allow_missing_facsimile=True,
    auto_watch_mei=False,
    verovio_options={"footer": "none", "scale": 35, "svgViewBox": True},
)
```

Relative local `<graphic target>` paths are resolved from the MEI file's
directory and embedded into the HTML as data URIs. HTTP(S) targets and existing
data URIs pass through unchanged. The viewer reads files only; it does not
alter the MEI or image.

For active editing, set `auto_watch_mei=True`. Event mode uses `watchdog` and
falls back to timed polling if file events are unavailable. In score-only mode,
**Check facsimile** looks for newly added records while retaining cached score
SVG. In linked mode, **Reload zones** re-parses the records; **Reload score**
also reruns Verovio.

The executable companion is
[`notebooks/mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb).

## API

::: camat.facsimile_viewer
