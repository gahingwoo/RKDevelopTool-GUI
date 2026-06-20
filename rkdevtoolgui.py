#!/usr/bin/env python3
"""Root-level launcher kept for backward compatibility.

The application uses explicit relative imports (``from .utils import ...``),
which require the modules to be loaded as part of a package.  This shim
manually registers ``rkdeveloptool_gui`` as a package so that the import
chain works from the source tree (``python rkdevtoolgui.py`` from the repo
root still works).
"""
import os
import sys
import importlib.util

_pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rkdeveloptool-gui")

# Register ``rkdeveloptool_gui`` as a namespace package so that relative
# imports inside its modules resolve correctly.
_spec = importlib.util.spec_from_file_location(
    "rkdeveloptool_gui",
    os.path.join(_pkg_dir, "__init__.py"),
    submodule_search_locations=[_pkg_dir],
)
_pkg = importlib.util.module_from_spec(_spec)
sys.modules["rkdeveloptool_gui"] = _pkg
_spec.loader.exec_module(_pkg)

from rkdeveloptool_gui.rkdevtoolgui import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
