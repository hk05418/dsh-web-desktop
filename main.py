"""Nuitka build entry point (launcher).

Nuitka compiles this file + the ``dsh_desktop`` package it imports. The
``python -m dsh_desktop`` / ``uv run dsh-desktop`` entry points (``__main__.py``)
remain for running from source; this launcher is only used by the Nuitka build
(see scripts/build_nuitka.py).
"""
from __future__ import annotations

import sys

from dsh_desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
