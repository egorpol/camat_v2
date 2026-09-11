# Independent binary queries

`camat.binary_query` searches queries defined independently of a source score,
using the pitch labels and time resolution of both bundles. MIDI search retains
the query's voicing plus an explicit semitone transposition. Chroma search uses
all twelve pitch classes and circular transposition; it does not slide a cropped
pitch-class patch or infer MIDI pitches from folded rows.

`search_binary_query(host, query, transpositions="all")` adds an unconstrained
MIDI scan: every valid pitch row and time column in the host is tested, retaining
the query's voicing and reporting the uniform semitone shift. With a chroma host,
`"all"` instead tests the twelve distinct circular shifts. The default `(0,)`
keeps the original pitches/classes. A `minmax` MIDI host searches its observed
register; use a `full` host to include all 128 rows. Only completely contained
kernel placements are scored. This changes placement, not pitch intervals.

`plot_query_heatmaps(..., rank=None)` marks every shortlisted hit using 1-based
rank labels. `aggregate_transpositions=True` displays the maximum across shifts
at each time/scale, leaving the returned full maps unchanged. This is an overview
of a broader search, not a map of one fixed transposition or a significance test.
Pass the same rank-ordered `colors` to it and `plot_matched_sources` to link
heatmap hits to their source piano-roll windows.

Search results separate `placements` (every finite score before filtering) from
`matches` (the selected shortlist). Both tables include required, shared and
missing active-cell counts, normalized `overlap`, and `loss_fraction`. Occupancy
loss is `missing_cells / required_cells`; it equals `1 - score` only when the
selected metric is normalized overlap. Extra source activity does not increase
this loss. Counts are pitch/class × time bins, not numbers of missing notes or
chords; shorter tempo variants have different denominators.

Use `rank_query_matches(result["placements"], min_score=2/3, top_n=None, ...)`
to review all candidates above a new threshold without recomputing the search.
The score cutoff is inclusive on full-precision values; time-IoU suppression is
separate, and `top_n=None` removes the display cap. Compare raw placement counts
with retained-window counts before interpreting how many occurrences were found.
`plot_query_loss_examples` compares real windows at one fixed scale and pitch
shift, distinguishing shared requirements, missing requirements and extra notes.

For the chord study's D–A–D template, moving MIDI preserves the I–V–I / T–D–T
relationship under uniform transposition: −2 semitones requests C–G–C. Its labels
name the placed query, not verified source harmonies; even complete occupancy
does not determine tonal function. The study reports these placed chord names
and separates the single-hit stage audit from the full threshold distribution.

Pitch accuracy matters before searching: the Verovio parser resolves implied
key-signature pitches and measure accidentals from the source MEI. Otherwise a
notated F♯ can enter both grids as F, making a correctly specified chord query
appear to fail. The task notebook retains the original notation for this check.

The task-driven
[`chord_progression_search.ipynb`](../../notebooks/chord_progression_search.ipynb)
compares fixed MIDI, chroma and moving MIDI, checks artificial transposition and
revoicing, then follows all shortlisted candidates into the original notation. For full
source-note provenance and filled piano-roll windows, combine the returned
variant and placement with `binary_match_sources`, `plot_matched_source` (one
hit), or `plot_matched_sources` (all hits, gray notes for shared membership) in
[binary roundtrip helpers](binary_roundtrip.md).

::: camat.binary_query
