"""WayFinder Tkinter application package.

The GUI lives in :mod:`wayfinder.app.app`; this package re-exports the
application class so the entry point can import it directly.
"""

from .app import WayFinderApp

__all__ = ["WayFinderApp"]
