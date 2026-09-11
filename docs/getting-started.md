---
title: Getting started
---

# Getting started

## Install CAMAT

Use Python 3.11 or later in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install camat
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.

## Parse your first score

This example uses a tiny score shipped with CAMAT. After installation it runs
offline, without a corpus download, Jupyter, or an external music editor.

```python
from importlib.resources import as_file, files
from camat import parse_files_quiet

example = files("camat").joinpath("examples", "facsimile_viewer_demo.mei")
with as_file(example) as score:
    results, _, _ = parse_files_quiet(
        [str(score)],
        backend="none",
        display_preview_df_pitch=False,
        display_preview_df_events=False,
        show_progress=False,
    )

notes = results[0]["df_pitch"]
print(f"Parsed {len(notes)} notes")
```

Expected output:

```text
Parsed 8 notes
```

`parse_files_quiet` suppresses parser diagnostics for this small example;
use `parse_files` when you want to see those messages.
`df_pitch` holds note rows; `df_events` holds non-note events. Verovio is the
default parser for common-notation MEI. For your own score, replace the packaged
example with a local MEI path. Convert other formats first using
[Convert to MEI](guides/formats.md).

## Run the showcase notebooks

The notebooks live in the repository, separately from the PyPI package.
Install CAMAT and copy **only** the tutorials and example files:

```bash
python -m pip install camat
camat-fetch-tutorials
python -m jupyterlab camat_tutorials/notebooks
```

That sparse copy does not include documentation sources, tests, or the
development archive. On [Jupyter4NFDI](https://hub.nfdi-jupyter.de) or
Google Colab, see [Cloud notebooks](cloud-notebooks.md).

To develop CAMAT itself, clone the repository so the installed code and
tutorials match:

```bash
git clone https://github.com/egorpol/camat_v2.git
cd camat_v2
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[notebooks]"
python -m ipykernel install --user --name camat --display-name "Python (CAMAT)"
python -m jupyterlab notebooks
```

On Windows, use the PowerShell activation command above. In JupyterLab,
select **Python (CAMAT)** as the notebook kernel when you used the development
install. Start with
[Render MEI](../notebooks/mei_render.ipynb),
[Inspect a score and facsimile](../notebooks/mei_facsimile_viewer.ipynb), or
[Duration semantics](../notebooks/duration_semantics_examples.ipynb) for
packaged or embedded examples. Then follow the [notebook roadmap](notebooks.md).

Saved outputs let you preview the examples on GitHub. Interactive widgets need
a running Jupyter kernel; a static preview cannot operate their controls.
Run cells from the top after restarting the kernel.

Some corpus examples need a download on their first run. In the Bach analysis
notebooks, enable `RUN_FETCH` in the configuration cell if the local source is
not cached, or set the source path to your own MEI file. Check each notebook's
configuration before enabling network access or writing results.

## Optional tools and tested platforms

- MuseScore-native conversion requires an installed MuseScore executable; see
  [format conversion](guides/formats.md).
- RELAX NG editorial validation uses `xmllint` from libxml2; other checks have
  their own switches in the [editorial workflow](guides/edition-building.md).
- Remote corpora, IIIF images, and remote MEI sources require network access.

CI tests Linux (Ubuntu) with Python 3.11–3.14. Windows and macOS are not covered
by the automated matrix yet. Dependency versions are resolved for each Python
version; CI saves the installed versions with its
[release-test results](releasing.md#tested-dependency-baseline).
