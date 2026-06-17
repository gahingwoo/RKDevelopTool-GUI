#!/usr/bin/env python3
"""Root-level launcher kept for backward compatibility.

The application code lives in the ``rkdeveloptool-gui/`` directory. This thin
shim puts that directory on ``sys.path`` and runs the real entry point, so the
historical ``python rkdevtoolgui.py`` (from the repo root) keeps working.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rkdeveloptool-gui")
)

from rkdevtoolgui import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    sys.exit(main())
