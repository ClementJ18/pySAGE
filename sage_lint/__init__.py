"""A linter and formatter for SAGE ini game data, built on sage_ini."""

from sage_utils.extras import package_version

__all__ = [
    "__version__",
    "package_version",
]

__version__ = package_version()
