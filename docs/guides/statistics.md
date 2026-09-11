---
title: Statistics
---

# Statistics

Use this part of [workflow 3](analysis.md) to summarize a score or compare a
selected passage or voice with the complete score. Work directly with CAMAT's
note and event tables; a binary matrix is not needed for these summaries.

## Start with a musical question

- Which pitches, pitch classes, or durations occur most often?
- Which melodic intervals or successive-pitch transitions occur?
- Where within the measure do notes begin?

Use common-notation MEI as the source. The tutorial parses its own file, so
it can be your first CAMAT analysis notebook. If you already have parsed
results, use `df_pitch` for note distributions and retain `df_events` and
measure context for analyses that depend on events or position in the measure.
See [Parse music into CAMAT representations](parsing-representations.md) for
those tables.

## Tutorial and available summaries

Tutorial notebook:
[`df_statistics.ipynb`](../../notebooks/df_statistics.ipynb)
(CMN only). It parses one MEI file for itself and shows:

- pitch and pitch-class distributions;
- metric or logical duration distributions (see also
  [`duration_semantics_examples.ipynb`](../../notebooks/duration_semantics_examples.ipynb));
- a monophony check before sequential analyses;
- successive-pitch transition heatmaps and melodic intervals;
- onset positions within measures (uses `df_events` / parse `results`).

Optional comparison stays simple: one full score plus one filtered selection.

## Summarize pitch and duration

With `df_pitch` from a parsed score:

```python
from camat import build_duration_counts, build_pitch_counts

pitch_counts, pitch_axis = build_pitch_counts(df_pitch, axis_option="pitch")
duration_counts, duration_axis = build_duration_counts(
    df_pitch,
    duration_column="Duration",
)
```

The explicit duration column matters: encoded segment duration, logical tied
duration, and measured performance duration answer different questions.

## Interpret the result

State which score, voices, or measures you included and which duration column
you used. Note counts and duration-based summaries describe different aspects
of the music. Sequential interval or transition analyses need a meaningful
note sequence; use the tutorial's monophony check before interpreting them as
a melodic line.

Retain the original MEI and note identifiers when filtering a table, so you
can inspect the passages behind a distribution in the score.

## Continue according to your question

- [Duration semantics](../../notebooks/duration_semantics_examples.ipynb)
  explains encoded segment, logical, and performed duration.
- [Analysis utilities](../api/analysis_utils.md) documents the statistical
  helpers and plotting functions.
- [Pattern search](pattern-search.md) addresses the separate question of where
  a musical pattern occurs.
- The [analysis learning track](../notebooks.md#workflow-3-analyse-music-statistics-and-pattern-search)
  groups the tutorials by the question they answer.
