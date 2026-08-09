---
title: Tutorial
---

# Tutorial

## Installation

```bash
pip install camat
```

## Quick Start

```python
from camat import get_parse_files, run_pattern_search

parse_files = get_parse_files()
results, dfs_by_name, last_df = parse_files(["path/to/score.mei"])

# Example: run pattern search on matrix/kernels
# out = run_pattern_search(matrix_source, kernel_source)
```

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

The parser accepts MEI. Convert other formats first with
`scripts/test_verovio_conversion.py` or `testing_verovio_conversion.ipynb`.
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

For strict partitura-only behavior, set:

- `allow_music21_fallback=False`
