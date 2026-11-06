---
title: Facsimile columns
---

# Facsimile columns

`add_facsimile_columns` adds the page, the image and the zone of each row's
bar to a CAMAT note or event table, so a row in an analysis can be traced back
to the scanned page. It reads the MEI file the table was parsed from and joins
on the `xml_id` column that CAMAT's parsers write. The table you pass in is not
changed: you get a copy with the same rows in the same order and nine new
columns at the end.

The link is **bar-level**. It goes from a row's `xml_id` to the element with
that `xml:id`, to the `<measure>` holding it, and through `measure/@facs` to the
zone, its surface and its graphic. So it names the bar on the page, and never
where inside the bar a note sits.

## Example

```python
from importlib.resources import files

from camat import add_facsimile_columns, parse_files

mei = str(files("camat").joinpath("examples", "facsimile_viewer_demo.mei"))
results, _, _ = parse_files(
    [mei],
    backend="none",
    display_preview_df_pitch=False,
    display_preview_df_events=False,
)
notes = add_facsimile_columns(results[0]["df_pitch"], mei)
print(notes[["Pitch", "zone_id", "page", "zone_ulx", "zone_uly", "zone_status"]].head(3))
```

```text
  Pitch      zone_id page  zone_ulx  zone_uly zone_status
0    C4  demo-zone-1    1        60       150      linked
1    D4  demo-zone-1    1        60       150      linked
2    E4  demo-zone-2    1       390       150      linked
```

`df_events` works the same way, through each event's own `xml_id`.

`mei` takes what [`read_facsimile_model`](facsimile_viewer.md) takes: a local
path or an HTTP(S) link, including a GitHub `blob` page. A relative path is
resolved from `repo_root`, which defaults to the CAMAT checkout or workspace,
and otherwise to the current directory.

## New columns

| Column | Holds |
| --- | --- |
| `zone_id` | the `xml:id` of the bar's zone |
| `surface_id` | the `xml:id` of the zone's `<surface>`, or `surface-N` when it has none, where N is its position among the surfaces |
| `page` | `surface/@n` as a string, or the surface's position when `@n` is absent |
| `image` | `graphic/@target` as written in the MEI, so a relative path stays relative |
| `zone_ulx`, `zone_uly`, `zone_lrx`, `zone_lry` | the zone's corners as written in the MEI |
| `zone_status` | whether the row linked, and if not, why |

`zone_status` is always filled in:

| `zone_status` | Meaning |
| --- | --- |
| `linked` | The row's element sits in a bar that has a zone. |
| `no xml_id` | The row has no id, as with an `<annot>` or `<tempo>` encoded without `xml:id`. |
| `id not in file` | No element in this MEI has that id, as with a table parsed from another version of the file. |
| `outside measure` | The element exists but is not in a bar, as with a clef or a key or meter signature in a `<staffDef>`. |
| `missing facs` | The element's bar has no `@facs`. |
| `facsimile unavailable` | The MEI has no usable facsimile and `allow_missing_facsimile=True` was passed. Every row gets this status. |

For every status but `linked`, the eight zone cells are missing values. The
corner columns are nullable `Int64` unless the table has a split bar (see
below).

A note tied across a barline is one row by default, and that row keeps the id
of the first note, so it links to the bar where the tie starts. With
`collapse_tied_pitch_events=False` each tied note has its own row and its own
bar.

## Bars with several zones

A bar broken across a system or page break can list several zones in `@facs`.
The rows still stay one to one: each of the eight zone cells then holds one
value per zone, separated by spaces, in `@facs` order. The k-th value of every
cell belongs to the k-th zone. Repeated values are kept so the positions line
up.

| Column | Cell for a bar split over two pages |
| --- | --- |
| `zone_id` | `zone-a zone-b` |
| `surface_id` | `surface-4 surface-5` |
| `page` | `4 5` |
| `image` | `page4.jpg page5.jpg` |
| `zone_ulx` | `1 2` |

The columns do not say which of the zones holds a given note, only that the
note is in this bar.

If any row has a split bar, the four corner columns are strings throughout, so
split the cell and convert its values to read them as numbers.

## Errors

| Situation | Result |
| --- | --- |
| The MEI has no usable facsimile | `FacsimileUnavailableError`, a `RuntimeError`, unless `allow_missing_facsimile=True` |
| An invalid facsimile record, such as `@facs` that points to nothing or to a zone not typed `measure`, or a zone that runs past its image | `RuntimeError`, with or without `allow_missing_facsimile` |
| The table has no `xml_id` column | `ValueError` |
| The table already has one of the nine new column names, as a table that has been through this function does | `ValueError` |
| A split bar where a value contains a space, as a multi-URI `@target` does | `ValueError`, because its cells could not be read by position |

A bar with one zone keeps such a value as written.

## API

::: camat.facsimile_table
