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

parse_files = get_parse_files("partitura")
results, dfs_by_name, last_df = parse_files(["path/to/score.mxl"])

# Example: run pattern search on matrix/kernels
# out = run_pattern_search(matrix_source, kernel_source)
```

## Common-Notation Backend Choice

For common music notation, use `partitura` as the default backend.

- `partitura` is the primary parser in CAMAT for current workflows.
- It has the best MEI support, including reliable `xml_id` extraction and
  explicit `df_events` output.
- It is the backend that new parsing features should target first.

Use `music21` only when you specifically need the legacy parser behavior or
want a fallback implementation. The `music21` backend is still supported for
common-notation files, but it is not the recommended first choice.

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
