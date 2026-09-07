---
title: Contributing
---

# Contributing

Use [GitHub Issues](https://github.com/egorpol/camat_v2/issues) to report bugs
or discuss a proposed change. Include the CAMAT and Python versions, the parser
or conversion route, a minimal reproducer, and the expected and actual result.
Only attach scores or images you can share.

## Development setup

Clone the repository and activate a Python 3.11+ virtual environment as shown
in [Getting started](getting-started.md). From the repository root:

```bash
python -m pip install -e ".[test,notebooks]" -r docs/requirements.txt
python -m pytest tests --ignore=tests/release -q
python -m mkdocs build --strict
python -m mkdocs serve
```

Open the local documentation at <http://127.0.0.1:8000/>. Run MkDocs through
the same Python environment that imports CAMAT, so its dependencies and the
Material theme are available.

Tests run from a Git checkout: they use fixtures and archived notebook probes
that are deliberately excluded from the PyPI source distribution. The
installed-wheel tests run separately through
[the release matrix](releasing.md#local-compatibility-matrix).

## Pull requests

Keep a change focused and explain the resulting behaviour. Add regression
coverage for a bug fix, update the relevant guide when behaviour changes, and
add a short entry under `Unreleased` in [the changelog](../CHANGELOG.md).
Include the checks you ran in the pull request description.

## Notebooks and data

Showcase notebooks belong in `notebooks/`. Each should introduce its workflow,
declare its inputs and outputs, and run from a fresh kernel without depending
on another notebook's state. Prefer a small offline example and make external
tools, downloads, and file writes explicit in the configuration cells.

Preserve saved notebook outputs unless the change specifically calls for
updating them. Historical probes and basic experiments live in
[the archive](../CAMAT_old/README.md); the
[notebook roadmap](notebooks.md) is the supported tutorial sequence.

Put generated conversions in the ignored `converted_mei/` directory. Before
adding a score, scan, or schema, record its source and reuse terms alongside it
and update [third-party notices](../THIRD_PARTY_NOTICES.md) where applicable.
