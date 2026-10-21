"""Checks of the lazy package init: cheap ``import camat``, unchanged public API."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
import subprocess
import sys
import textwrap

import camat


INIT = Path(camat.__file__)


def _from_imports(nodes: list[ast.stmt]) -> dict[str, tuple[str, str]]:
    return {
        alias.asname or alias.name: (node.module, alias.name)
        for node in nodes
        if isinstance(node, ast.ImportFrom) and node.level == 1
        for alias in node.names
    }


def test_import_camat_loads_only_the_standard_library() -> None:
    script = textwrap.dedent(
        """
        import sys
        before = set(sys.modules)
        import camat
        loaded = {name.split(".")[0] for name in set(sys.modules) - before}
        print(sorted(name for name in loaded if name != "camat" and name not in sys.stdlib_module_names))
        assert camat.pattern_search.__name__ == "camat.pattern_search"
        try:
            camat.no_such_name
        except AttributeError:
            pass
        else:
            raise AssertionError("camat.no_such_name resolved")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=INIT.parents[1],
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_type_checking_imports_match_the_lazy_table_and_all() -> None:
    tree = ast.parse(INIT.read_text(encoding="utf-8"))
    block = next(
        node for node in tree.body
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
    )
    assert _from_imports(block.body) == camat._LAZY_ATTRS
    eager = _from_imports(tree.body)
    assert not set(eager) & set(camat._LAZY_ATTRS)
    assert set(camat._LAZY_ATTRS) | set(eager) | {"__version__"} == set(camat.__all__)


def test_public_names_resolve_to_their_submodule_objects() -> None:
    for name, (module, attr) in camat._LAZY_ATTRS.items():
        assert getattr(camat, name) is getattr(importlib.import_module(f"camat.{module}"), attr), name
    assert set(camat.__all__) <= set(dir(camat))


def test_names_shared_with_submodules_stay_functions() -> None:
    # mei_consistency_workflow imports both submodules under these names.
    importlib.import_module("camat.mei_consistency_workflow")
    from camat.convert_harm_startid_to_tstamp import convert_file
    from camat.link_pb_to_surface import link_file

    assert camat.convert_harm_startid_to_tstamp is convert_file
    assert camat.link_pb_to_surface is link_file
