"""PyQt6 desktop editor for a Create-a-Hero `.cah` file, in the style of the other SAGE
front ends (see app.py). Built on the shared sage_utils widgets and theme."""

from sage_utils.extras import package_version

__all__ = [
    "__version__",
    "package_version",
]

__version__ = package_version()
