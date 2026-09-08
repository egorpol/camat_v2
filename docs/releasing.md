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
5. Installs the wheel with the `test` extra (`pytest`) in a fresh venv,
   allowing pip to resolve the wheel's declared `requirements.txt` dependencies.
6. Runs `pip check`.
7. Saves the resolved package versions to
   `.release-runs/py<version>/installed-dependencies.json`.
8. Runs `tests/release/test_installed_package.py` from outside the checkout and
   verifies that `camat` was imported from the installed wheel.

Use `--allow-missing` only for partial development checks. A release run should
not skip any interpreter. `--reuse` is available for debugging, but should not
be used as release evidence.

## Tested dependency baseline

The automated matrix runs on Ubuntu with Python 3.11–3.14. Windows and macOS
are not yet covered by CI. Each wheel test resolves the declared dependencies
for its interpreter, runs `pip check`, and records the installed versions in
`installed-dependencies.json`. GitHub Actions retains these files in
`dependency-baseline-<python-version>` artifacts, tied to the workflow run and
commit. Download them from the run's **Artifacts** section when reproducing a
release environment.

This records tested combinations; it is not a lockfile or a claim that every
older dependency version works. Dependency minimums should be added when
supported by API requirements and tests. The `notebooks` extra adds JupyterLab;
several plotting and widget libraries remain runtime dependencies because the
current package imports them through its public API.

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

`.github/workflows/test.yml` runs on pushes to `main` and `beta/**`, pull
requests, and manual dispatches. It includes:

- the installed-wheel release runner on Python 3.11–3.14;
- the full checkout unit/regression suite on Python 3.11 (the oldest supported
  version), excluding the installed-wheel suite that runs separately;
- a strict MkDocs build on Python 3.11, matching Read the Docs.

The tag-driven release workflow calls this whole workflow first. Release
building and PyPI publishing wait for all six jobs to pass. Before building,
`scripts/prepare_release.py` checks the tag, both package version declarations,
and a nonempty, dated changelog section. The validated notes are passed to the
GitHub release as an artifact. Prerelease versions such as `0.2.2b1` are marked
as GitHub prereleases and do not replace the latest stable release.

Check the metadata locally without publishing anything:

```bash
python scripts/prepare_release.py --tag v0.2.1
```

Use the tag for the version being prepared.

To run the additional checks locally from the repository root:

```bash
python -m pip install -e ".[test]" -r docs/requirements.txt
python -m pytest tests --ignore=tests/release -q
python -m mkdocs build --strict
```

## Documentation and package versions

The documentation describes its source checkout. MkDocs reads the package
version from `pyproject.toml` and displays it in the site title. To try the
same code, install that checkout with `python -m pip install -e .`.
`python -m pip install camat` selects the latest published release; it does
not install unpublished beta changes. Use `--pre` only after a matching
prerelease has actually been published.

Links to notebooks, source manifests and archived probes are relative paths
in the Markdown sources, so GitHub resolves them on the branch being viewed.
For the built site, `scripts/docs_hooks.py` validates those repository paths
and links them to the exact Git commit used for the build. This works for
beta, main, release tags and detached CI/Read the Docs checkouts without
hardcoding `main` in every page.

When building a source snapshot without `.git`, set `CAMAT_DOCS_REF` to the
branch, tag or commit containing that snapshot. During local editing, links
still refer to the current commit; new files become available on GitHub after
they are committed and pushed.

## Documentation hosting

CAMAT's documentation is hosted on Read the Docs:

- [Stable documentation](https://camat-v2.readthedocs.io/en/stable/) describes
  the published release and is the main README, package metadata, and GitHub
  About destination.
- [Development documentation](https://camat-v2.readthedocs.io/en/latest/)
  follows `main`, including changes that have not been released yet.

Pushing to `main` updates the development docs. It does not move the `stable`
version to that commit: stable follows the release selected by Read the Docs.
For example, documentation added after the `v0.2.1` tag appears under `latest`
until a subsequent release includes it. Link new pages to `latest` explicitly
until they exist in stable, rather than adding a broken stable URL.

The build settings live in `.readthedocs.yaml`. MkDocs takes `site_url` from
`READTHEDOCS_CANONICAL_URL`, with the stable CAMAT URL as a local-build fallback,
so generated canonical links use the deployed domain and version path. See
[Read the Docs' MkDocs configuration guide](https://docs.readthedocs.com/platform/stable/intro/mkdocs.html).

For each release:

1. Confirm the release tag is active in Read the Docs and its build succeeds.
2. Check that `stable` selects the intended release and is the default public
   documentation version.
3. Open the stable site in a logged-out browser and check notebook links and
   any newly added pages. Move explicit development links to stable when their
   content is included in the release.

## Release checklist

1. Choose the release version and update both `pyproject.toml` and
   `camat/__init__.py`.
2. Move the relevant changelog entries from `Unreleased` into a dated version
   section.
3. Run the checkout tests, strict docs build, and
   `python scripts/test_release_matrix.py`; retain the passing summary.
4. Optionally rerun the large Verovio parity and robustness corpora.
5. Commit the release changes and create a matching `v<version>` tag.
6. Push the tag; the release workflow retests all supported Python versions
   before publishing to PyPI.
