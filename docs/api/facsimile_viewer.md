---
title: MEI facsimile viewer
---

# MEI facsimile viewer

`camat.facsimile_viewer` provides a reusable inspection layer for a local MEI
path or an HTTP(S) link, including GitHub `blob` pages. It always renders the
notation with Verovio. When the MEI includes usable facsimile records, it also
places measure zones over the image and links both representations
interactively.

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
- a `<graphic>` with `@target`, `@width`, and `@height` on every surface that
  contains measure zones;
- `<zone type="measure">` elements with coordinates and `xml:id` values;
- score measures whose `@facs` values point to those zone identifiers.

The viewer supports multiple facsimile surfaces. Its previous/next controls
change the Verovio score page and automatically select the surface referenced
by measures on that page. Hovering or clicking an individual measure selects
its exact linked surface and zone. Only links whose zone id occurs on no
surface are errors.

## Notebook source selection and local API

The companion notebook exposes one configuration value:

```python
from camat import launch_interactive_facsimile_viewer, read_facsimile_model

# Local, absolute or repository-relative:
MEI_SOURCE = "converted_mei/my_score.mei"

# Or remote, including a GitHub blob page:
MEI_SOURCE = "https://github.com/owner/repository/blob/main/path/score.mei"
```

Its default is the CAMAT corpus edition of
[Buxtehude's Sonata V in C major, Op. I](https://github.com/egorpol/DdT_1_vol_11/blob/main/11_buxtehude_sonatas_final/buxtehude_op1_05_sonata_c_major_corr.mei).
`read_facsimile_model` and `launch_interactive_facsimile_viewer` accept that
value directly. GitHub `blob` pages are converted to raw-file links, and remote
MEI is cached under `converted_mei/facsimile_viewer_sources/`.

The Python viewer API itself accepts a local MEI path or URL:

```python
from camat import launch_interactive_facsimile_viewer

viewer = launch_interactive_facsimile_viewer(
    "/path/to/score.mei",  # facsimile records are optional
    allow_missing_facsimile=True,
    show_verovio_warnings=False,
    auto_watch_mei=False,
    initial_score_zoom_percent=100,
    initial_facsimile_zoom_percent=100,
    zoom_step_percent=25,
    min_zoom_percent=50,
    max_zoom_percent=300,
    verovio_options={"footer": "none", "scale": 35, "svgViewBox": True},
)
```

The viewer toolbar zooms the score and facsimile independently without
rerunning Verovio. The percentage button resets its pane to the configured
initial zoom. Zoom is retained while changing score pages and facsimile
surfaces.

Relative local `<graphic target>` paths are resolved from the MEI file's
directory and embedded into the HTML as data URIs. HTTP(S) targets and existing
data URIs pass through unchanged. The viewer reads files only; it does not
alter the MEI or image.

For active editing, set `auto_watch_mei=True`. Event mode uses `watchdog` and
falls back to timed polling if file events are unavailable. In score-only mode,
**Check facsimile** looks for newly added records while retaining cached score
SVG. In linked mode, **Reload zones** re-parses the records; **Reload score**
also reruns Verovio.

## Annotation rendering

Verovio 6.2.1 preserves `<annot>` records internally and emits an SVG
`<g class="annot">` for annotations anchored with either `@plist` or
`@tstamp`. It does not engrave text stored in an annotation `<p>`, however.
The current CAMAT viewer does not add its own annotation overlay, so this text
is not visible in either pane.

The executable companion is
[`notebooks/mei_facsimile_viewer.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/mei_facsimile_viewer.ipynb).

## API

::: camat.facsimile_viewer
