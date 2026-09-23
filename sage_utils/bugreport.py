"""What a bug report needs before it is worth reading: which build the reporter is running,
what it was doing, and somewhere for the report to go.

A frozen desktop app gives none of that away - there is no console to copy a traceback from,
no `pip show` to ask for a version, and a windowed PyInstaller build writes its stderr nowhere
a user will find it. So every SAGE front end collects the same block here, and both the Help
menu and the crash handler hand it over ready to paste. Kept Qt-free (the Qt version is read
through a guarded import, and only if Qt is already importable) so a report can still be built
when the UI is the thing that failed.
"""

import platform
import sys
import urllib.parse
from collections.abc import Mapping

from sage_utils.extras import package_version

__all__ = [
    "DESCRIPTION_PLACEHOLDER",
    "environment",
    "ISSUES_URL",
    "new_issue_url",
    "qt_version",
    "report_text",
    "URL_BODY_LIMIT",
]

ISSUES_URL = "https://github.com/ClementJ18/pySAGE/issues"

# GitHub prefills a new issue from the query string, but serves a 414 rather than a form once
# the URL grows past about 8 KB. Staying well under it: the prefill is a convenience, and the
# dialog's Copy details is what carries a long report (a traceback) to the tracker.
URL_BODY_LIMIT = 4000

# What the reporter is asked to replace, and the marker a caller can look for to see whether
# they did. Written as a line of its own so it survives a copy-paste into the issue form.
DESCRIPTION_PLACEHOLDER = "(What were you doing, what happened, and what did you expect?)"


def qt_version() -> str | None:
    """The Qt version behind a running desktop app, or None when Qt is not loaded - which is
    both the CLI case and the one where importing Qt is what went wrong."""
    try:
        from PyQt6.QtCore import QT_VERSION_STR  # noqa: PLC0415 - guarded: keeps this Qt-free
    except ImportError:
        return None
    return QT_VERSION_STR


def environment(app: str, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The rows naming the build a report came from, followed by `extra` - whatever state the
    app itself knows is worth having (the open map, the loaded mods, the game data)."""
    rows = {
        "App": app,
        "pySAGE": package_version(),
        # An exe and a checkout fail differently: a bundle can be missing a data file that is
        # simply there in a source run, so which one this is belongs at the top of a report.
        "Build": "frozen exe" if getattr(sys, "frozen", False) else "source checkout",
        "Python": platform.python_version(),
        "Qt": qt_version() or "not loaded",
        "OS": f"{platform.system()} {platform.release()} ({platform.machine()})",
    }
    rows.update(extra or {})
    return rows


def report_text(
    app: str,
    *,
    extra: Mapping[str, str] | None = None,
    details: str | None = None,
    description: str = DESCRIPTION_PLACEHOLDER,
) -> str:
    """A whole report as Markdown, ready to paste into the issue form: a description to fill
    in, the environment rows, and `details` (a traceback, say) in a code fence."""
    lines = ["### What happened", "", description, "", "### Environment", ""]
    lines += [f"- **{label}:** {value}" for label, value in environment(app, extra).items()]
    if details:
        lines += ["", "### Details", "", "```", details.strip(), "```"]
    return "\n".join(lines) + "\n"


def new_issue_url(title: str, body: str = "", *, issues_url: str = ISSUES_URL) -> str:
    """A link that opens the issue form with `title` (and `body`, when it is short enough to
    travel in a URL) already filled in."""
    query = {"title": title}
    if body and len(body) <= URL_BODY_LIMIT:
        query["body"] = body
    return f"{issues_url}/new?{urllib.parse.urlencode(query)}"
