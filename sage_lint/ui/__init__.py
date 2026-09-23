"""PyQt6 desktop window over `sage_lint lint`, in the style of sage_ui / sage_wiki (see
app.py). Built on the shared sage_utils widgets and theme."""

from sage_utils.extras import package_version

__all__ = [
    "__version__",
    "package_version",
]

__version__ = package_version()
