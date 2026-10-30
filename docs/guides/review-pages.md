---
title: Review pages
---
# Review pages

`camat-review-page` makes a local page for a person to confirm corrected
readings against the printed source. After correcting a batch by hand, from
a lint report or with an assistant, write one question per card. The
reviewer compares the source with the notation, marks each answer and
copies a summary back to the editor.

The builder requires CAMAT 0.2.9 or newer. It renders the notation during
the build; the reviewer only needs a browser. Open the result as a local
file, without a server.

## What the reviewer sees

Each card has a heading, a status badge and a description, followed by three
columns:

- **Source:** a crop of the facsimile at the card's bars.
- **Before:** those bars rendered from the MEI at a git ref, normally `HEAD`
  (the last commit).
- **After:** those bars rendered from the working-tree file, including the
  corrections that have not been committed.

The default column captions are **Source**, **HEAD** and **now**. The
checkbox at the top hides the before column. A spec with
`"before_ref": null` omits it altogether and needs no git history. Further
images and their captions, such as a second witness, appear under the
columns.

Choose **ok** when the reading agrees with the source, **problem** when it
needs attention, or **clear** to remove a mark. Add an explanation in the
card's **Note** box. The status badge comes from the spec; it does not
preselect a reviewer's mark.

A card with `"rows": true` has one row per bar, each with its own marks.
Above each row, a line lists changed events matched by `xml:id`: pitch,
duration, onset (`tstamp`), staff and other attribute changes. `+` means an
added event and `−` a removed one. A line shows at most 12 events, then
"and N more". A card without rows puts the same list in a collapsed
**N changed events** section when there are changes. With no before
version, there is no change list. Keep event ids stable while correcting
the MEI so that the comparison can match them.

Marks and notes stay in the browser's local storage under the spec's
`storage_key`. Give each review a different key to keep its marks apart
from other reviews in the same browser. Another browser, another computer
or clearing site data starts empty. If the browser blocks local storage,
marks last only until the page is closed.

Use **Copy summary** to copy one line per card, then paste those lines back
to the editor. If the browser cannot copy automatically, the dialog lets
you select and copy the text. An unmarked card is shown as `-`; a card with
rows reports how many rows are marked and lists those marks. A note is
appended with ` — `.

## Build a review

Suppose `work.mei` has four bars with ids `m1` to `m4`, linked to a local
page image, `page.png`. Bars 1–3 have facsimile zones; bar 4 still needs one.
The file is tracked in git. In the last commit, bar 2 ends with C4 and bar
3's figure starts at `tstamp="1"`. In the working tree, the last note of bar
2 is D4 and the figure has moved to `tstamp="2"`.

Save this as `review.json` beside `work.mei` and `page.png`:

```json
{
  "$schema": "https://raw.githubusercontent.com/egorpol/camat_v2/v0.2.9/camat/schemas/review.schema.json",
  "title": "Corrections to confirm",
  "storage_key": "corrections-round-1",
  "description": "<p>Compare each corrected reading with the print, then copy your summary.</p>",
  "cards": [
    {
      "id": "m2",
      "label": "Bar 2",
      "mei": "work.mei",
      "measures": "2",
      "description": "<p>Is the last note <b>D4</b>?</p>"
    },
    {
      "id": "figures",
      "label": "Figures mm. 1-4",
      "mei": "work.mei",
      "measures": "1-4",
      "description": "<p>Check the position of each figure under the bass.</p>",
      "rows": true,
      "status": "partly"
    },
    {
      "id": "m34",
      "label": "Bars 3-4",
      "mei": "work.mei",
      "measures": ["#m3", "#m4"],
      "description": "<p>Check the reading across these bars; use the whole page for bar 4.</p>",
      "images": [
        {"src": "page.png", "caption": "Whole source page"}
      ]
    }
  ]
}
```

Run this in that folder:

```bash
camat-review-page review.json OUT
```

`OUT` must not exist, even as an empty folder. Each review goes into a new
folder so that an earlier review someone has already marked is never
overwritten. For another round, choose a new output folder and a new
`storage_key`.

The command prints counts of cards, rows, renders and crops, then warnings
and the path to open. This example has three cards and four rows. It warns
that `figures` and `m34` have no facsimile zone for bar 4.

Open `OUT/index.html` in a browser. The first card compares bar 2 in the
source, at `HEAD` and now; its collapsed change list reads `note C4→D4`.
The second card gives each bar its own marks, and bar 3's change line reads
`harm 6/4: tstamp 1→2` if its figure is encoded as 6/4. Its fourth row says
"no facsimile zone" in the source column. The third card shows bars 3–4
together, a crop covering bar 3's zone, and the whole source page below.

For example, mark **Bar 2** ok, mark only bar 2 of **Figures mm. 1-4** as
problem and write "Check the figure" in that card's note, then mark
**Bars 3-4** ok. **Copy summary** gives:

```text
Bar 2: ok
Figures mm. 1-4: 1/4 marked (m. 2 problem) — Check the figure
Bars 3-4: ok
```

## What the MEI needs

- **`xml:id` on every shown `<measure>`.** Verovio needs these ids to select
  the bars.
- **Unambiguous bar selections.** If a requested `@n` occurs more than once,
  for example when movements restart numbering, the builder refuses that
  selection and asks for `#xml:id` values. Use an array such as
  `["#m3", "#m4"]`; it includes both endpoints and every bar between them
  in document order.
- **For the source column:** each bar's `@facs` points to a `<zone>` on a
  `<surface>` with a `<graphic target="…">`. The zone gives `ulx`, `uly`,
  `lrx` and `lry`. Record the graphic's `width` and `height` in pixels so
  that the crop uses the right coordinate system. A local graphic target is
  relative to the MEI file.
- **For the before column:** the MEI file must be readable at `before_ref`
  in its git repository. If the file exists there but the selected bars do
  not, the before column shows a placeholder.

Bars without a usable zone are warnings, not build errors. A selection
with no zones says "no facsimile zone" in the source column; if only some
bars have zones, its crop covers those bars. Several bars on one page give
one crop: the union of their zones, with padding. Bars on two pages give
two crops. With `rows`, each bar is cropped separately.

## Spec reference

camat ships `camat/schemas/review.schema.json`. The `$schema` URL in the
example lets an editor complete keys and flag mistakes. The schema checks
keys, types and patterns; the build checks the rest, including files,
unique card ids, bar selections and the MEI at the git ref. The build
ignores the `$schema` URL itself. Unknown spec keys are errors.

At the top level:

- `title` is required: non-empty text for the page title and heading.
- `storage_key` is required: 1–64 lower-case letters, digits or `-`,
  starting with a letter or digit.
- `cards` is required: a non-empty list of cards, described below.
- `description` is an optional HTML introduction under the heading.
- `before_ref` defaults to `"HEAD"`. Give another git ref to compare with
  that version, or `null` to omit the before column.
- `labels` overrides column captions: `source` defaults to `"Source"`,
  `before` to the ref, and `after` to `"now"`.
- `verovio` supplies options merged over the defaults of the
  [web edition](web-edition.md#site-config), with `scale: 50`,
  `header: none` and `breaks: auto` for these excerpts. Values may be text,
  numbers or booleans.
- `crop` sets `padding` and `size`, described below.
- `version` is optional; `1` is the only version and the default.
- `$schema` is an optional schema URL or path for editors.

Each card has:

- `id` (required): a unique id for its anchor and stored mark. Start with a
  letter or digit; the rest may also contain `_`, `.` and `-`.
- `mei` (required): the MEI path, relative to the spec file's folder.
- `measures` (required): `"12"` for one bar, `"12-14"` for a range of bar
  numbers, or `["first", "last"]` with `@n` values or `#xml:id` values.
  A one-item array, such as `["#m3"]`, selects a single bar. Use arrays
  when an id or bar number contains a hyphen.
- `label`: the heading and name in the summary; defaults to `id`.
- `description`: HTML above the columns.
- `status`: `"check"` (default, "to check"), `"partly"` ("partly confirmed")
  or `"confirmed"`. It sets the badge and colour.
- `images`: extra images below the columns. Each has a required `src`
  (local path relative to the spec, or an http(s) URL) and optional
  `caption`. Local images are copied; URLs stay as browser-loaded images.
- `rows`: `false` by default; `true` gives one row per bar and marks each
  row separately. There is still one note per card.
- `width`: Verovio page width, an integer of at least 100. The default is
  1000 for one bar, 1800 for several bars, or 900 per row.

The introduction and card descriptions are inserted as HTML as written.
Only use text you trust.

## Facsimile crops

`crop.padding` is `[left, top, right, bottom]` in graphic pixels, all
non-negative integers. Its default is `[200, 80, 200, 240]`, with extra
space below for figures under the bass. `crop.size` defaults to
`"!1400,1600"`: fit within that box while keeping the proportions. Other
supported IIIF sizes are `"max"`, `"full"`, `"1200,"` (width), `",1600"`
(height) and `"1200,1600"` (exact dimensions).

For a IIIF graphic whose target ends in
`/full/{size}/{rotation}/{quality}.{format}`, the image server cuts the
region. The builder reads its `info.json`, scales zone coordinates by
`info.json` width divided by the graphic's `width`, and requests a pixel
region at `crop.size`. Library masters are often larger than the image
linked in the MEI. This route needs a numeric graphic width; other targets
are cut locally with Pillow, including local files and plain image URLs.
Local crops also scale coordinates when a graphic width is available;
without one, they use the zone coordinates unchanged.

Building fetches one region per card or bar per source page from a IIIF
image server, as well as its `info.json`. Check the library's terms of use
for automated requests. Downloads go to camat's cache,
`~/.cache/camat/downloads`, or `CAMAT_DOWNLOAD_CACHE_DIR` if set. Rebuilding
with the same requests reuses cached downloads.

## The output folder

The build writes `index.html`, `review.css` and `review.js`, SVG notation in
`renders/`, JPEG crops in `crops/`, and any copied extra images in `images/`.
Open `index.html` directly. Send the whole folder to a reviewer so that the
page can find its images and styles. Extra images given as URLs still need
an internet connection. Marks and notes are kept in the browser, not in
these files.

Every check runs before the output is written. `ReviewSpecError` lists all
problems found together, so you can fix them in one pass. From Python:

```python
from camat.review_page import ReviewSpecError, build_review_page

try:
    report = build_review_page("review.json", "OUT")
except ReviewSpecError as error:
    print("\n".join(error.problems))
```

`build_review_page` also takes a spec as a dict. Pass `base_dir` to resolve
its paths, for example `build_review_page(spec, "OUT", base_dir="edition")`;
without it, paths are relative to the current folder. The report contains
`out`, `cards`, `rows`, `renders`, `crops`, `warnings`, `files` and `bytes`.

## Limits

- Renders use Verovio's own line breaks, rather than encoded page and system
  breaks.
- A card spanning a whole system gets a wide, short crop that looks small
  in its column. Split the question into smaller cards or use `rows`.
- The source column needs facsimile zones. The extra whole-page image in
  the example helps a reviewer look up a missing bar, but does not supply
  its zone.
- The page records no provenance. It is a working tool for confirming
  readings; use the [web edition](web-edition.md) for publication.
