# CAMAT

[![PyPI version](https://img.shields.io/pypi/v/camat.svg)](https://pypi.org/project/camat/)
[![Python versions](https://img.shields.io/pypi/pyversions/camat.svg)](https://pypi.org/project/camat/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/egorpol/camat_v2/blob/main/LICENSE)

CAMAT is a Python toolkit for symbolic music parsing, analysis, pattern search, and score rendering.

Supports Python 3.10+

## Installation

```bash
pip install camat
```

## What Is Included

- Parsing helpers for `partitura` and `music21` backends.
- Experimental Verovio-backed common-notation MEI parsing.
- Timeline/rap Humdrum parsing with rhythm-only duration and onset-position summaries.
- Pattern search and similarity utilities.
- Piano-roll and overlay visualization helpers.
- Verovio-based rendering utilities.

## Parser Guidance

For common music notation, use the `partitura` backend as the primary parser.
It is the most complete backend in CAMAT for current work: better MEI support,
reliable `xml_id` extraction, explicit `df_events` output, and the strongest
alignment with the rest of the parsing pipeline.

The `music21` backend is kept as a legacy-compatible alternative. It can now
emit `df_pitch` and `df_events` for common-notation files as well, but it
should be treated as a fallback implementation rather than the default parser.

An experimental Verovio-backed MEI parser is available as
`parse_files(..., parsing_backend="verovio")` or `"vrv"`. It is intended for
native Verovio parity work against Partitura and currently supports
common-notation MEI only; Partitura remains the recommended backend until the
parity harness is fully stable.

For MCFlow-style rap Humdrum timelines, use `parse_files(...,
parsing_backend="timeline")`. This returns `df_timeline` rows with stable MEI
ids and optional rhythm-analysis columns suitable for timeline MEI rendering.

## Documentation

This repo includes an MkDocs project in `docs/` and a Read the Docs config in
`.readthedocs.yaml`.

Local preview:

```bash
pip install -r docs/requirements.txt
mkdocs serve
```

Then open `http://127.0.0.1:8000/`.

## Repository Layout

- `camat/`: package source used for PyPI distribution.
- `CAMAT_old/`: legacy development notebooks and experiments.
- `CHANGELOG.md`: release notes.
- `test_corpus/`: test data and source links.
  
## License

MIT (see `LICENSE`).
