"""The primitives every view module builds on: the `safe` degradation guard, raw-field
readers, generic model traversal, and the tiny display formatters."""


def safe(getter, default=None):
    try:
        return getter()
    except Exception:  # noqa: BLE001  (lazy conversion may raise; UI degrades gracefully)
        return default


def upgrade_names(raw) -> list[str]:
    """Split a raw upgrade field (a name or whitespace-separated names) into names."""
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    names: list[str] = []
    for value in values:
        names.extend(str(value).split())
    return names


def all_modules(obj):
    """Every behavior module on `obj` and the templates it inherits from."""
    owner = obj
    while owner is not None:
        yield from getattr(owner, "modules", ())
        owner = getattr(owner, "parent", None)


def find_behavior(obj, behavior_type):
    """The first module of `behavior_type` on `obj` or a template it inherits from."""
    owner = obj
    while owner is not None:
        for module in getattr(owner, "modules", ()):
            if isinstance(module, behavior_type):
                return module
        owner = getattr(owner, "parent", None)
    return None


def percent(value) -> str:
    """A damage scalar as a rounded percentage: 1.0 -> '100%', 1.254 -> '125%'."""
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return str(value)


def fmt_stat(value) -> str:
    """A numeric stat rounded to a whole number for display, or an em dash when absent."""
    return "-" if value is None else str(round(float(value)))
