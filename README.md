# CAMAT

[![PyPI version](https://img.shields.io/pypi/v/camat.svg)](https://pypi.org/project/camat/)
[![Python versions](https://img.shields.io/pypi/pyversions/camat.svg)](https://pypi.org/project/camat/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/egorpol/camat_v2/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-Sphinx-blue.svg)](https://github.com/egorpol/camat_v2/tree/main/docs)

CAMAT is a Python toolkit for symbolic music parsing, analysis, pattern search, and score rendering.

Supports Python 3.10+

## Installation

```bash
pip install camat
```

## What Is Included

- Parsing helpers for `music21` and `partitura` backends.
- Pattern search and similarity utilities.
- Piano-roll and overlay visualization helpers.
- Verovio-based rendering utilities.

## Documentation

This repo includes a Sphinx project in `docs/` and a Read the Docs config in
`.readthedocs.yaml`.

Local preview:

```bash
pip install -r docs/requirements.txt
sphinx-build -b html docs docs/_build/html
python -m http.server --directory docs/_build/html 8000
```

Then open `http://127.0.0.1:8000/`.

## Repository Layout

- `camat/`: package source used for PyPI distribution.
- `CAMAT_old/`: legacy development notebooks and experiments.
- `CHANGELOG.md`: release notes.
- `test_corpus/`: test data and source links.
  
## License

MIT (see `LICENSE`).
