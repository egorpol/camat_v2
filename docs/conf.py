from __future__ import annotations

from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

project = "CAMAT"
author = "Egor Polyakov"

try:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        _pyproject = tomllib.load(fh)
    release = _pyproject.get("project", {}).get("version", "0.0.0")
except Exception:
    release = "0.0.0"

version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

# Build docs without requiring full optional runtime stack on RTD.
autodoc_mock_imports = [
    "bokeh",
    "bokeh.io",
    "bokeh.models",
    "bokeh.palettes",
    "bokeh.plotting",
    "bokeh.transform",
    "IPython",
    "IPython.display",
    "ipycanvas",
    "ipywidgets",
    "matplotlib",
    "matplotlib.pyplot",
    "music21",
    "numpy",
    "pandas",
    "partitura",
    "requests",
    "tqdm",
    "verovio",
]

html_theme = "sphinx_rtd_theme"
html_static_path: list[str] = []
