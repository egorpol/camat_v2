"""Make ``camat`` importable when a notebook runs from this folder.

Jupyter often starts with its working directory set to ``notebooks/``.
This helper prefers an installed CAMAT package. If the package is missing,
it adds a local source checkout to ``sys.path``. Cloud sessions should
install with ``pip install camat`` and copy tutorials with
``camat-fetch-tutorials`` (see the cloud-notebooks documentation).
"""

from __future__ import annotations

from pathlib import Path
import sys


def _find_source_checkout() -> Path | None:
    here = Path(__file__).resolve().parent
    searched = (here, here.parent, Path.cwd().resolve(), *Path.cwd().resolve().parents)
    for candidate in searched:
        if (candidate / "camat" / "__init__.py").is_file():
            return candidate
    return None


try:
    from camat.notebook_workspace import locate_workspace, activate_workspace

    _located = locate_workspace()
    if _located is not None:
        CAMAT_ROOT = activate_workspace(_located)
    else:
        CAMAT_ROOT = _find_source_checkout()
        if CAMAT_ROOT is not None:
            CAMAT_ROOT = activate_workspace(CAMAT_ROOT)
except ImportError:
    CAMAT_ROOT = _find_source_checkout()
    if CAMAT_ROOT is not None and str(CAMAT_ROOT) not in sys.path:
        sys.path.insert(0, str(CAMAT_ROOT))

if CAMAT_ROOT is None:
    try:
        import camat as _camat_pkg  # noqa: F401
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "CAMAT was not found. Install it with: python -m pip install camat\n"
            "To copy tutorial notebooks and examples without cloning the "
            "full repository: camat-fetch-tutorials"
        ) from exc
    CAMAT_ROOT = Path.cwd().resolve()
elif (CAMAT_ROOT / "camat" / "__init__.py").is_file() and str(CAMAT_ROOT) not in sys.path:
    sys.path.insert(0, str(CAMAT_ROOT))
