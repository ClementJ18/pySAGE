"""PyQt6 desktop window for building and combining `asset.dat` files, in the style of
sage_lint's UI (see app.py). Built on the shared sage_utils widgets and theme."""

from sage_utils.extras import package_version

__all__ = [
    "__version__",
    "package_version",
]

__version__ = package_version()
