---
title: Release testing
---

# Release testing

CAMAT's release gate tests the built wheel—not an editable checkout—on every
supported stable Python version from 3.11 through 3.14.

## Local compatibility matrix

Install the four interpreters, then run from the repository root:

```bash
python scripts/test_release_matrix.py
```

The runner discovers `python3.11` through `python3.14` on `PATH` and Conda
environments named like `py311`, `py312`, and so on. An explicit interpreter
can be supplied when discovery is not suitable:

```bash
python scripts/test_release_matrix.py \
  --versions 3.12 3.14 \
  --python 3.12=/path/to/python3.12 \
  --python 3.14=/path/to/python3.14
```

Environment variables such as `CAMAT_PYTHON_311` and `CAMAT_PYTHON_314` are
also supported.

By default every run:

1. Deletes and recreates only the ignored `.release-venvs/`, `.release-runs/`,
   and `.release-dist/` paths.
2. Builds a wheel in an isolated build environment.
3. Checks the wheel metadata with Twine.
4. Creates a fresh venv for each requested Python version.
5. Installs `requirements-test.txt` and the wheel, allowing pip to resolve the
   wheel's declared `requirements.txt` dependencies.
6. Runs `pip check`.
7. Runs `tests/release/test_installed_package.py` from outside the checkout and
   verifies that `camat` was imported from the installed wheel.

Use `--allow-missing` only for partial development checks. A release run should
not skip any interpreter. `--reuse` is available for debugging, but should not
be used as release evidence.

## Smoke-test coverage

The installed-package route checks:

- package version metadata and all top-level public exports;
- Verovio as the default parser, including MEI notes, rests, events, IDs, and
  measure offsets;
- explicit Partitura and music21 compatibility parsers;
- MusicXML-to-MEI conversion and Verovio SVG rendering;
- pitch, pitch-class, duration, melodic-interval, and pattern-search analysis;
- rap timeline parsing, rhythm enrichment, MEI generation, duplicate ID checks,
  and Verovio loading;
- mensural duration and meter normalization helpers.

The broader corpus parity and robustness scripts remain useful before a beta,
but the installed-wheel smoke suite is intentionally small, deterministic, and
offline so it can run for every pull request and release tag.

Python 3.10 is intentionally unsupported. Current Verovio releases do not
publish a CPython 3.10 wheel, so CAMAT requires Python 3.11 or newer instead of
silently selecting an older Verovio release.

## Continuous integration and publishing

`.github/workflows/test.yml` runs the same release runner in a Python
3.11–3.14 matrix for pushes to `main`, pull requests, and manual dispatches.
The tag-driven release workflow calls that compatibility workflow first. Wheel
building and PyPI publishing cannot begin until all four jobs pass.

## Release checklist

1. Choose the release version and update both `pyproject.toml` and
   `camat/__init__.py`.
2. Move the relevant changelog entries from `Unreleased` into a dated version
   section.
3. Run `python scripts/test_release_matrix.py` and retain the passing summary.
4. Optionally rerun the large Verovio parity and robustness corpora.
5. Commit the release changes and create a matching `v<version>` tag.
6. Push the tag; the release workflow retests all supported Python versions
   before publishing to PyPI.
