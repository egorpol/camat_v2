# CAMAT

CAMAT is a Python toolkit for symbolic music parsing, analysis, pattern search, and score rendering.

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

## Repository Layout

- `camat/`: package source used for PyPI distribution.
- `CAMAT_revamped/`: legacy development notebooks and experiments.
- `CHANGELOG.md`: release notes.

## License

MIT (see `LICENSE`).
