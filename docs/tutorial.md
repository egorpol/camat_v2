---
title: Backend and specialized parsing
---

# Backend and specialized parsing

This guide covers backend choice and source types that do not follow the
default common-notation MEI contract. Begin with
[Parse and represent MEI](guides/parsing-representations.md) for the standard
`df_pitch` and `df_events` workflow.

Mensural MEI and timeline/rap Humdrum parsing are **experimental** and have
not been tested thoroughly. Common-notation MEI is the supported schema; see
[Known limitations](known-limitations.md).

## Common-Notation Backend Choice

For common music notation, CAMAT uses `verovio` as the default backend.

- The analysis format is common-notation MEI.
- `parse_files(...)` and `get_parse_files()` select `verovio` unless overridden.
- `partitura` remains the reference backend for parser parity tests.

Use the default directly, or select it explicitly:

```python
from camat.parser_registry import parse_files

results, dfs_by_name, last_df = parse_files(
    ["path/to/score.mei"],
    parsing_backend="verovio",
    backend="none",
)
```

The parser accepts MEI. Convert other formats first; see
[Convert to MEI](guides/formats.md) and `notebooks/camat_formats.ipynb`.
Formats Verovio does not support natively are imported by music21, exported to
MusicXML, and then converted to final MEI by Verovio.

## Timeline / Rap Humdrum Parsing

For MCFlow-style rap Humdrum timelines, use the dedicated `timeline` backend:

```python
from camat import timeline_to_mei
from camat.parser_registry import parse_files

results, dfs_by_name, df_timeline = parse_files(
    ["path/to/song.rap"],
    parsing_backend="timeline",
    add_rhythm_analysis=True,
)

mei_text = timeline_to_mei(results[0]["df_timeline"], metadata=results[0]["metadata"])
```

Timeline parsing creates `df_timeline` instead of `df_pitch`. The optional
rhythm enrichment adds duration-distribution and onset-position columns that
can be rendered later with `timeline_to_mei(...)` or `save_timeline_mei(...)`.

## Mensural MEI Normalization

Use the helper script to normalize mensural duration labels in MEI files for
partitura compatibility:

```bash
python scripts/normalize_mensural_mei.py path/to/input.mei -o path/to/output.mei
```

You can override injected default meter:

```bash
python scripts/normalize_mensural_mei.py path/to/input.mei -o path/to/output.mei --meter-count 2 --meter-unit 2
```

## Parser Defaults

`parse_files_partitura` applies this preprocessing by default:

- `normalize_mensural_durations=True`
- `inject_missing_meter_signature=True` (defaults to `4/4`)
- `prefer_verovio_for_mensural=True`
- `try_verovio_mei_conversion=True`
- `verovio_mensural_to_cmn=True`
- `verovio_duration_equivalence=None`
- `verovio_mensural_score_up=False`

For strict partitura-only behaviour, set:

- `allow_music21_fallback=False`
