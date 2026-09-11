---
title: Cloud notebooks
---

# Cloud notebooks

The PyPI package is the CAMAT library. Tutorial notebooks and the example
files in [`test_corpus/`](../test_corpus) live in the git repository and are
not installed with `pip install camat`.

Copy **only those two folders**. You do not need documentation sources, tests,
or the development archive.

```bash
python -m pip install camat
camat-fetch-tutorials
```

That creates `camat_tutorials/notebooks/` and `camat_tutorials/test_corpus/`
in the current directory. The command uses a sparse git clone of the tag that
matches the installed CAMAT version, then `main` if that tag is missing.
Python 3.11 or later and `git` are required.

The same steps from a notebook cell:

```python
%pip install -q camat
from camat.notebook_workspace import prepare_notebook
prepare_notebook()
```

`prepare_notebook()` is a no-op when it already sees a CAMAT checkout or a
copied tutorial workspace. Editorial notebooks resolve paths such as
`test_corpus/buxtehude_pages` from that workspace. Packaged demos such as
`camat/examples/facsimile_viewer_demo.mei` come from the installed wheel.

Then follow the [notebook roadmap](notebooks.md).

## Jupyter4NFDI

[Jupyter4NFDI](https://hub.nfdi-jupyter.de) is a JupyterLab service (login via
Helmholtz AAI). Files under `/home/jovyan` persist after a restart.

1. Open <https://hub.nfdi-jupyter.de>, sign in, and start JupyterLab on
   JSC-Cloud.
2. Confirm the kernel is Python 3.11 or later (`python --version` in a
   terminal, or `import sys; print(sys.version)` in a notebook).
3. In a **Terminal** tab:

   ```bash
   python -m pip install camat
   camat-fetch-tutorials
   ```

4. In the file browser, open `camat_tutorials/notebooks/` and start with
   [`mei_render.ipynb`](../notebooks/mei_render.ipynb) or
   [`cloud_setup.ipynb`](../notebooks/cloud_setup.ipynb).

You can run the same two commands with `!` or `%pip` in a notebook instead of
the terminal. A kernel that already has CAMAT installed does not need a full
repository clone.

To keep the install across sessions, create a user virtual environment and
register it as a kernel; see
[Jupyter4NFDI kernel environments](https://nfdi-jupyter.de/users/jupyterlab/4.3/kernels_venv/).
On the default JupyterLab image, files outside `/home/jovyan` are discarded
when the server stops.

Optional tools such as MuseScore and `xmllint` are often absent in the cloud
image. Conversion notebooks skip MuseScore when the executable is missing;
RELAX NG editorial validation needs `xmllint`. See
[Getting started](getting-started.md#optional-tools-and-tested-platforms).

## Google Colab

Colab runtimes currently use Python 3.12, which meets CAMAT's requirement.
Open the setup notebook:

[Open cloud_setup.ipynb in Colab](https://colab.research.google.com/github/egorpol/camat_v2/blob/main/notebooks/cloud_setup.ipynb)

or paste the two cells above into a new notebook.

Opening a single tutorial from GitHub with **Open in Colab** used to fail:
Colab copies only that `.ipynb`, so `import setup_camat` could not see the
repository and `test_corpus/` was missing. The Workflow 1 editing and conversion
notebooks now install CAMAT and copy those folders in their first code cell.

Colab still starts a **new runtime per notebook tab**. Files written under
`/content` in one tab are not visible in another. Run the first cell of each
tutorial you open, or stay in one runtime and open a copied notebook from the
left-hand file browser without disconnecting.

Interactive Verovio widgets (paste-and-render, facsimile viewer) are more
reliable in JupyterLab than in Colab. If a widget stays blank, enable Colab's
custom widget manager (the setup helper does this when it detects Colab) or
run that notebook on Jupyter4NFDI. Plotting and table notebooks are the better
Colab starting point.

Workflow 2 and 3 notebooks that load Bach from a URL only need
`python -m pip install camat` in that runtime. Run `prepare_notebook()` as
well if `import camat` fails or you want `test_corpus/` on disk.

## Local Jupyter

On your own machine you can use the same `camat-fetch-tutorials` command after
`pip install camat`, or clone the repository if you are developing CAMAT. See
[Getting started](getting-started.md#run-the-showcase-notebooks).
