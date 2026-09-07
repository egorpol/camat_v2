---
title: Parse and represent MEI
---

# Parse and represent MEI

This is **CAMAT workflow 3**. Start with
[`mei_parse_tables.ipynb`](../../notebooks/mei_parse_tables.ipynb)
(parse one score to `df_pitch` / `df_events` and a piano roll), then
[`mei_annotate_selection.ipynb`](../../notebooks/mei_annotate_selection.ipynb)
(select notes and write MEI annotations). Duration semantics remain in
[`duration_semantics_examples.ipynb`](../../notebooks/duration_semantics_examples.ipynb).

Parsing is the boundary between the MEI document and Python. CAMAT reads the
score without replacing it and returns representations suited to inspection,
filtering, plotting, and analysis.

## Minimal parse

```python
from camat import parse_files

results, dfs_by_name, last_df = parse_files(
    ["path/to/score.mei"],
    backend="none",
    display_preview_df_pitch=False,
    display_preview_df_events=False,
)

score = results[0]
df_pitch = score["df_pitch"]
df_events = score["df_events"]
```

The default backend is Verovio and its common-notation parser accepts MEI. Use
the [conversion workflow](formats.md) before this step for other formats.

## The returned objects

| Object | Scope | Use it for |
| --- | --- | --- |
| `results` | ordered list, one record per source | keeping each score's tables, measure offsets, source, and backend together |
| `results[i]["df_pitch"]` | one row per parsed note or note segment | pitch, onset, duration, voice, note metadata, and note-level analysis |
| `results[i]["df_events"]` | non-note events | rests, barlines, directions, dynamics, text, spans, and measure metadata |
| `dfs_by_name` | flat mapping of generated names to DataFrames | selecting tables interactively or by name in notebooks |
| `last_df` | final source's pitch table | quick experiments with one source only |

For reusable code, prefer `results[i]["df_pitch"]` over `last_df`; the latter
silently changes when more files are added.

## Representation ladder

| Representation | Keeps | Abstracts away |
| --- | --- | --- |
| MEI | document structure, metadata, notation, editorial markup, identifiers | nothing; this is the source document |
| `df_pitch` | note timing, pitch, voice, MEI ids, selected note attachments | most XML hierarchy and layout |
| `df_events` | non-note musical and textual events plus anchors | most XML hierarchy and engraving detail |
| piano roll | pitch and duration positioned in time | document structure and most notation metadata |
| binary matrix | occupied pitch/time cells on an explicit grid | continuous timing within a grid cell and, depending on settings, octave/range detail |

The farther down this table an analysis moves, the more important it is to keep
metadata that connects the result to its source.

## `df_pitch`

The stable core columns are:

| Column | Meaning |
| --- | --- |
| `Measure` | parsed measure position |
| `Local Onset` | onset within the measure |
| `Global Onset` | onset on the score timeline, in quarter-note units |
| `Duration` | metric segment duration, in quarter-note units |
| `Pitch` | spelled pitch name |
| `MIDI` | numeric pitch |
| `Voice` | CAMAT voice label |
| `xml_id` | link to the originating MEI note |

Optional enrichment adds note attachments such as tie, slur, tuplet, fermata,
articulation, ornament, and technical information. Tie handling changes whether
encoded segments or logical notes occupy rows; see
[`duration_semantics_examples.ipynb`](../../notebooks/duration_semantics_examples.ipynb).

## `df_events`

`df_events` prevents non-note information from being forced into note rows. It
contains timing and identity fields plus event-specific data. The `type` column
distinguishes rests, barlines, directions, dynamics, lyrics, tempo, ties,
slurs, ornaments, setup changes, and related MEI events. Anchor columns such as
`start_xml_id` and `end_xml_id` connect spans to notes where the MEI provides
that relationship.

## Parser backends are adapters

| Backend | Role |
| --- | --- |
| `verovio` | default common-notation MEI parser |
| `partitura` | reference implementation used for parser-parity testing |
| `music21` | compatibility parser and conversion bridge |
| `mensural` | experimental mensural-MEI path; not thoroughly tested |
| `timeline` | experimental rap-Humdrum timeline parser (`df_timeline`); not thoroughly tested |

Backends are not different analysis formats to choose casually. Start with
Verovio for common-notation MEI. Mensural and timeline paths are experimental;
see [Known limitations](../known-limitations.md).

## Preserve identity and context

Keep `xml_id`, `measure_offsets`, the original MEI, and the parser/backend
version with stored results. They make it possible to explain an analytical
row, trace a matrix cell to its notes, or highlight a match in the rendered
score.

Continue with [Analyse representations](analysis.md).

