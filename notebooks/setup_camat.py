"""Make ``camat`` importable when a notebook runs from this folder.

Jupyter often starts with its working directory set to ``notebooks/``,
so ``import camat`` fails unless the repository root is on ``sys.path``.
Importing this module first adds that root.
"""

from __future__ import annotations

from pathlib import Path
import sys


def _find_camat_root() -> Path | None:
    here = Path(__file__).resolve().parent
    searched = (here, here.parent, Path.cwd().resolve(), *Path.cwd().resolve().parents)
    for candidate in searched:
        if (candidate / "camat" / "__init__.py").is_file():
            return candidate
    return None


_root = _find_camat_root()
if _root is None:
    raise ModuleNotFoundError(
        "CAMAT was not found. Open this notebook from the CAMAT repository, "
        "or install it with: pip install -e ."
    )
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
