## 0.1.0 - first release

- Refactor for PyPI release (`pip install camat`).
- Copied package modules from `CAMAT_revamped/py_scripts` to `camat/`.
- Updated internal package references from `py_scripts.*` to `camat.*` / relative imports.
- Aligned `requirements.txt` with imports used by `camat/*.py`.
- Added packaging metadata via `pyproject.toml` and `MANIFEST.in`.
- Reformatted `README.md` for PyPI project page readability.
- Added mensural MEI preprocessing helpers and a dedicated script (`scripts/normalize_mensural_mei.py`) for partitura compatibility, including optional default meter injection for files missing time signatures.
- Added a partitura-first retry path that converts unsupported MEI structures through Verovio before parsing (reducing reliance on the legacy music21 fallback).

## 0.1.1
