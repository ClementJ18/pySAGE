"""Per-session wiki credentials. The username is remembered in a plaintext JSON file;
the password, when the user opts in, goes to the OS secret store via `keyring`. Every
keyring call is best effort - with no usable backend it silently does nothing and the
caller keeps the password in memory for the session.
"""

from dataclasses import dataclass

import keyring
from keyring.errors import KeyringError

from sage_utils.config import read_json, write_json

USERNAME_FILE = "username.json"


@dataclass(frozen=True)
class Credentials:
    """A user-account login: the account's username and password."""

    username: str
    password: str


def save_username(username: str, app: str = "sage_wiki") -> None:
    """Remember the username (only) for next launch (best effort, no secret stored)."""
    write_json(app, USERNAME_FILE, {"username": username})


def load_username(app: str = "sage_wiki") -> str:
    """The remembered username, or ``""`` when none is saved or it is unreadable."""
    data = read_json(app, USERNAME_FILE, {})
    return data.get("username", "") if isinstance(data, dict) else ""


def save_password(username: str, password: str, app: str = "sage_wiki") -> bool:
    """Store the password for `username` in the OS secret store. Returns False when no
    keyring backend is available (the secret is then kept only in memory)."""
    try:
        keyring.set_password(app, username, password)
    except KeyringError:
        return False
    return True


def load_password(username: str, app: str = "sage_wiki") -> str:
    """The password stored for ``username``, or ``""`` when none is saved or the
    keyring is unavailable."""
    try:
        return keyring.get_password(app, username) or ""
    except KeyringError:
        return ""


def delete_password(username: str, app: str = "sage_wiki") -> None:
    """Forget any stored password for ``username`` (best effort; a missing entry or
    unavailable keyring is ignored)."""
    try:
        keyring.delete_password(app, username)
    except KeyringError:
        pass
