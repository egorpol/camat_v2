# CAMAT

[![PyPI version](https://img.shields.io/pypi/v/camat.svg)](https://pypi.org/project/camat/)
[![Python versions](https://img.shields.io/pypi/pyversions/camat.svg)](https://pypi.org/project/camat/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/egorpol/camat_v2/blob/main/LICENSE)

CAMAT is a Python toolkit for symbolic music parsing, analysis, pattern search, and score rendering.

Supports Python 3.11+

## Installation

```bash
pip install camat
```

## What Is Included

- Verovio-backed common-notation MEI parsing (the default parser).
- Compatibility parsers for `partitura` and `music21`.
- Timeline/rap Humdrum parsing with rhythm-only duration and onset-position summaries.
- Pattern search and similarity utilities.
- Piano-roll and overlay visualization helpers.
- Verovio-based rendering utilities.

## Parser Guidance

For common music notation, CAMAT now defaults to the `verovio` backend. The
analysis pipeline is MEI-first, so call `parse_files(...)` without a
`parsing_backend` for `.mei` sources, or select it explicitly with
`parsing_backend="verovio"` / `"vrv"`.

Convert non-MEI sources before parsing. Verovio-native inputs are converted
directly; other music21-readable formats go through
`music21 -> MusicXML -> Verovio -> MEI`. MuseScore-native files use MuseScore
for the MusicXML export. The conversion workflow is available in
`scripts/test_verovio_conversion.py` and `testing_verovio_conversion.ipynb`.

The `partitura` backend remains the ground-truth/reference implementation for
parser parity tests. The `music21` backend remains available for compatibility
and as the converter's import bridge, but neither is the registry default.

For MCFlow-style rap Humdrum timelines, use `parse_files(..., parsing_backend="timeline")`. This returns `df_timeline` rows with stable MEI
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

## Release Testing

The release gate builds the wheel and installs it into fresh virtual
environments for Python 3.11 through 3.14:

```bash
python scripts/test_release_matrix.py
```

See [Release testing](docs/releasing.md) for interpreter discovery, partial
matrix commands, smoke-test coverage, and the tag-to-PyPI checklist.

## Repository Layout

- `camat/`: package source used for PyPI distribution.
- `CAMAT_old/`: legacy development notebooks and experiments.
- `CHANGELOG.md`: release notes.
- `test_corpus/`: test data and source links.

## License

MIT (see `LICENSE`).
