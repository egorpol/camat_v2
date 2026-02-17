# CAMAT

CAMAT is a Python toolkit for symbolic music parsing, analysis, pattern search, and score rendering.

Optimized for Python => 3.11

## Installation

```bash
pip install camat
```

## What Is Included

- Parsing helpers for `music21` and `partitura` backends.
- Pattern search and similarity utilities.
- Piano-roll and overlay visualization helpers.
- Verovio-based rendering utilities.

## Quick Start

```python
from camat import get_parse_files, run_pattern_search

parse_files = get_parse_files("music21")  # or "partitura"
results, dfs_by_name, last_df = parse_files(["path/to/score.mxl"])

# Example: run pattern search on a matrix and kernel
# out = run_pattern_search(matrix_source, kernel_source)
```

## Mensural MEI Helper

If your MEI files use mensural duration labels (for example `semibrevis`), you can normalize them for partitura compatibility:

```bash
python scripts/normalize_mensural_mei.py path/to/input.mei -o path/to/output.mei
```

You can override injected default meter if needed:

```bash
python scripts/normalize_mensural_mei.py path/to/input.mei -o path/to/output.mei --meter-count 2 --meter-unit 2
```

`parse_files_partitura` applies this preprocessing automatically by default:
- `normalize_mensural_durations=True`
- `inject_missing_meter_signature=True` (defaults to `4/4`, configurable)
- `prefer_verovio_for_mensural=True` (detects mensural MEI markers and runs Verovio first)
- `try_verovio_mei_conversion=True` (retries unsupported MEI structures through Verovio, still using partitura)
- `verovio_mensural_to_cmn=True`
- `verovio_duration_equivalence=None` (set if you want explicit mensural-to-CMN scaling)
- `verovio_mensural_score_up=False`

If you want a strict partitura-only workflow (no music21 fallback), set:
- `allow_music21_fallback=False`

## Repository Layout

- `camat/`: package source used for PyPI distribution.
- `CAMAT_revamped/`: legacy development notebooks and experiments.
- `CHANGELOG.md`: release notes.
- test_corpus - various test data
  
## License

MIT (see `LICENSE`).
