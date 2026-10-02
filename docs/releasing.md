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
2. Builds a source archive in an isolated build environment, then builds the
   wheel from that archive, matching CI.
3. Checks both files' metadata with Twine.
4. Creates a fresh venv for each requested Python version.
5. Installs the wheel with the `test` extra (`pytest`) in a fresh venv,
   allowing pip to resolve the wheel's declared `requirements.txt` dependencies.
6. Runs `pip check`.
7. Saves the resolved package versions to
   `.release-runs/py<version>/installed-dependencies.json` and the tested wheel's
   filename and SHA-256 checksum to `tested-wheel.json` in the same directory.
8. Runs `tests/release/test_installed_package.py` from outside the checkout and
   verifies that `camat` was imported from the installed wheel.

Use `--allow-missing` only for partial development checks. A release run should
not skip any interpreter. `--reuse` is available for debugging, but should not
be used as release evidence.

Run the required validation gate with `xmllint` available on `PATH`:

```bash
python scripts/test_release_matrix.py --validation --versions 3.11 3.14
```

This installs the wheel with its `test` and `validation` extras, runs the
focused MEI validation, consistency and edition-pipeline regressions against
the installed package, and checks the packaged schema, SchXslt compiler and
license. A valid tiny score must pass; separate RELAX NG and Schematron
violations must fail. The tests verify that validation leaves the input bytes
unchanged. The runner saves `validation-results.xml` and rejects empty test
reports, skipped tests and any failures. Validation reports are retained below
`.release-runs/py<version>/pytest/`. The ordinary matrix continues to test the
basic installation separately.

To test the same wheel in separate local runs, build the distributions once
and supply that wheel to both commands:

```bash
python -m pip install "build>=1.2" "twine>=5"
python -m build
python -m twine check dist/*
python scripts/test_release_matrix.py --wheel dist/camat-<version>-py3-none-any.whl
python scripts/test_release_matrix.py --wheel dist/camat-<version>-py3-none-any.whl \
  --validation --versions 3.11 3.14
```

Replace `<version>` with the package version. Each invocation recreates
`.release-runs/`, so retain its evidence before starting the next run.

## Tested dependency baseline

The automated matrix runs on Ubuntu with Python 3.11–3.14. Windows and macOS
are not yet covered by CI. Each wheel test resolves the declared dependencies
for its interpreter, runs `pip check`, and records the installed versions in
`installed-dependencies.json`. Each run also records its tested wheel's SHA-256
checksum in `tested-wheel.json`. GitHub Actions retains these files in
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
- the fixed offline Bach chorale, Hummel prelude and `basic.mei` fixture,
  with input hashes, expected note/measure counts and input byte preservation;
- explicit Partitura and music21 compatibility parsers;
- MusicXML-to-MEI conversion and Verovio SVG rendering;
- pitch, pitch-class, duration, melodic-interval, and pattern-search analysis;
- rap timeline parsing, rhythm enrichment, MEI generation, duplicate ID checks,
  and Verovio loading;
- mensural duration and meter normalization helpers.

The broader corpus parity and robustness scripts remain useful before a beta,
but the installed-wheel smoke suite is intentionally small, deterministic, and
offline so it can run for every pull request and release tag.

For the small offline robustness set, run:

```bash
python scripts/test_verovio_parser_robustness.py \
  --source test_corpus/parser_robustness/sources.txt \
  --json .release-runs/parser-robustness.json
```

The [parser baseline](../test_corpus/parser_robustness/README.md) records its fixed
inputs and provenance. The runner reports selected/tested/pass/fail counts.
An empty selection or a missing source list fails and writes a fresh empty
report, so a previous passing report cannot be reused as this run's evidence.
The Hummel count comparison accounts for the intentionally filtered
zero-duration grace notes; missing ordinary notes still fail the check.

Python 3.10 is intentionally unsupported. Current Verovio releases do not
publish a CPython 3.10 wheel, so CAMAT requires Python 3.11 or newer instead of
silently selecting an older Verovio release.

## Continuous integration and publishing

`.github/workflows/test.yml` runs on pushes to `main` and `beta/**`, pull
requests, and manual dispatches. It includes:

- one shared build of the source archive and its wheel, with Twine checks and
  SHA-256 checksums;
- the installed-wheel release runner on Python 3.11–3.14;
- the full checkout unit/regression suite on Python 3.11 (the oldest supported
  version), excluding the installed-wheel suite that runs separately;
- the required installed-wheel validation gate on Python 3.11 and 3.14,
  with SaxonC and `xmllint`, requiring zero skipped tests;
- a strict MkDocs build on Python 3.11, matching Read the Docs.

All installed-wheel jobs download the same `dists` artifact and verify both
files against `release-checksums.txt` from the `release-checksums` artifact
before testing. These artifacts, along with each job's `tested-wheel.json`,
identify the exact files checked by the matrix.

The tag-driven release workflow first runs a metadata preflight, then calls
this whole test workflow. After every test and documentation job passes,
the publishing job downloads those same release files, verifies their
checksums again, and uploads them to PyPI without rebuilding. The checksum
file is retained separately from the distributions. The preflight runs
`scripts/prepare_release.py` to check the tag, both package version declarations,
and a nonempty, dated changelog section. Both plain headings such as
`## [0.2.5] - 2026-10-02` and reference-linked headings such as
`## [0.2.5][0.2.5] - 2026-10-02` are supported. The `Unreleased` section is
ignored. The checker also rejects GitHub `@mention`
tokens such as `@facs` in those notes, because release pages would otherwise
list unrelated accounts under Contributors. Write MEI attributes as `` `facs` ``
or `` &#64;facs `` instead. The validated notes are passed to the
GitHub release as an artifact. Prerelease versions such as `0.2.2b1` are marked
as GitHub prereleases and do not replace the latest stable release.

Check the metadata locally without publishing anything:

```bash
python scripts/prepare_release.py --tag v0.2.5
```

Use the tag for the version being prepared.

To run the additional checks locally from the repository root:

```bash
python -m pip install -e ".[test,validation]" -r docs/requirements.txt
python -m pytest tests --ignore=tests/release -q
python -m mkdocs build --strict
```

Also provide libxml2's `xmllint` on `PATH` for RELAX NG integration tests.
The basic checkout/wheel jobs install the `test` extra; validation-dependent
tests may skip there. The separate validation jobs install all processors and
run the focused tests without skips before publishing is allowed. GitHub
Actions retains their JUnit results, installed dependency versions and wheel
validation reports as `validation-evidence-<python-version>` artifacts. See
[the baseline](../test_corpus/validation_baseline/README.md) for input provenance.

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
3. Run the checkout tests, strict docs build, and both installed-wheel commands
   above against the same wheel;
   retain the passing summaries and validation evidence.
4. Run the small offline robustness set above. Optionally rerun the large
   Verovio parity and robustness corpora.
5. Commit the release changes and create a matching `v<version>` tag.
6. Push the tag; the release workflow builds once, tests that wheel on all
   supported Python versions, and publishes the same verified files to PyPI.
