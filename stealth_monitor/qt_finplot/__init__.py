"""
Qt + finplot based viewing layer for the stealth monitor project.

This package exposes a ``run`` helper so the client can be launched via
``python -m stealth_monitor.qt_finplot`` or imported elsewhere.
"""

from .app import run

__all__ = ["run"]

