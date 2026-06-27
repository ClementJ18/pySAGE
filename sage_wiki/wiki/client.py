"""Editing the Edain wiki through the MediaWiki action API: a thin wrapper over `mwclient`
that hides the token dance and exposes what the diff workflow needs (fetch/exists/search/
save/upload).

Authentication takes a normal account (`clientlogin`) or a `User@botname` bot password
(the legacy `login` action). Fandom usually rejects a normal password over the API, so a
bot password from `Special:BotPasswords` is the reliable choice; an interactive second
step (2FA, captcha) is not supported. The password is never persisted.
"""

import io
from dataclasses import dataclass
from urllib.parse import quote

import mwclient
from mwclient.errors import APIError, InsufficientPermission, LoginError, ProtectedPageError

from sage_wiki.names import split_file_namespace

EDAIN_HOST = "edain.fandom.com"
FANDOM_PATH = "/"
DEFAULT_USER_AGENT = "sage_wiki/0.1 (Edain wiki updater)"

# Fandom typically rejects a normal account's password over the API; a bot
# password is the way in. Appended to login failures to point the user there.
_BOT_PASSWORD_HINT = (
    " If your normal password works on the website but not here, create a bot "
    "password at Special:BotPasswords and log in as User@botname with its secret."
)


class WikiError(Exception):
    """A wiki operation (connect, login, fetch or save) failed."""


@dataclass(frozen=True)
class SaveResult:
    """The outcome of an edit. `no_change` is True when the submitted text matched the page
    exactly, so the wiki recorded no new revision (`new_revid` is then None)."""

    title: str
    old_revid: int | None
    new_revid: int | None
    no_change: bool


class WikiClient:
    """A session against one wiki, connecting lazily on first use. Reads work anonymously;
    `save`/`upload`/`delete` require a prior `login`."""

    def __init__(
        self,
        host: str = EDAIN_HOST,
        path: str = FANDOM_PATH,
        scheme: str = "https",
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._host = host
        self._path = path
        self._scheme = scheme
        self._user_agent = user_agent
        self._site: mwclient.Site | None = None
        self._all_titles: set[str] | None = None  # cached article-title index for link validation

    @property
    def site(self) -> mwclient.Site:
        """The underlying mwclient Site, created (and the wiki contacted) on first access.
        Connection failures surface as `WikiError`."""
        if self._site is None:
            try:
                self._site = mwclient.Site(
                    self._host,
                    path=self._path,
                    scheme=self._scheme,
                    clients_useragent=self._user_agent,
                    force_login=False,  # allow anonymous reads before login
                )
            except (APIError, OSError, ValueError) as exc:
                raise WikiError(f"could not connect to {self._host}: {exc}") from exc
        return self._site

    @property
    def logged_in(self) -> bool:
        return bool(self.site.logged_in)

    def login(self, username: str, password: str) -> None:
        """Authenticate a normal account (`clientlogin`) or a `User@botname` bot password
        (the legacy `login` action). Raises `WikiError` on bad credentials or an unsupported
        interactive step (2FA, captcha)."""
        try:
            if "@" in username:
                self.site.login(username=username, password=password)  # bot password
                result = True
            else:
                result = self.site.clientlogin(username=username, password=password)
        except LoginError as exc:
            detail = f"{exc.code}: {exc.info}" if getattr(exc, "info", None) else str(exc)
            raise WikiError(
                f"login failed for {username!r} — {detail}.{_BOT_PASSWORD_HINT}"
            ) from exc
        if result is not True:
            # clientlogin returned a continuation (captcha, 2FA, Fandom login screen) we
            # can't drive headlessly.
            raise WikiError(
                f"login for {username!r} needs an interactive step (captcha or 2FA), "
                f"which is not supported.{_BOT_PASSWORD_HINT}"
            )

    def page_url(self, title: str) -> str:
        """The browser URL of article `title` on this wiki (spaces canonicalised to
        underscores), for opening the page in an external browser."""
        slug = quote(title.strip().replace(" ", "_"), safe="/:()._-")
        return f"{self._scheme}://{self._host}/wiki/{slug}"

    def fetch_wikitext(self, title: str) -> str:
        """The page's current wikitext, or ``""`` when the page does not exist."""
        return self.site.pages[title].text()

    def fetch_image(self, filename: str) -> bytes | None:
        """The raw bytes of `File:<filename>` (prefix optional), or None when the file does
        not exist. Used to show a page's current infobox image, so a missing file is a soft
        None rather than an error."""
        _, name = split_file_namespace(filename.strip())
        if not name:
            return None
        try:
            image = self.site.images[name]
            if not image.imageinfo:  # no such file or no current revision
                return None
            return image.download()
        except (APIError, OSError) as exc:
            raise WikiError(f"could not fetch image {filename!r}: {exc}") from exc

    def exists(self, title: str) -> bool:
        return bool(self.site.pages[title].exists)

    def search_titles(self, prefix: str, limit: int = 20) -> list[str]:
        """Article titles starting with `prefix` (main namespace), for autocomplete."""
        if not prefix:
            return []
        pages = self.site.allpages(prefix=prefix, namespace="0", max_items=limit)
        return [page.name for page in pages]

    def all_titles(self) -> set[str]:
        """Every main-namespace article title on the wiki, fetched once and cached. Used to
        validate the internal links a page draft guesses, so a single bulk query stands in
        for one existence check per candidate name."""
        if self._all_titles is None:
            try:
                pages = self.site.allpages(namespace="0", max_items=None)
                self._all_titles = {page.name for page in pages}
            except APIError as exc:
                raise WikiError(f"could not list page titles: {exc}") from exc
        return self._all_titles

    def category_members(self, category: str, namespace: str = "0") -> list[str]:
        """Article titles belonging directly to `category` (prefix optional, main namespace
        by default). Nested subcategories are not included."""
        name = category.strip()
        if name.lower().startswith("category:"):
            name = name[len("category:") :].strip()
        if not name:
            return []
        try:
            members = self.site.categories[name].members(namespace=namespace)
            return [page.name for page in members]
        except APIError as exc:
            raise WikiError(f"could not list category {category!r}: {exc}") from exc

    def upload(self, data: bytes, filename: str, description: str = "", comment: str = "") -> None:
        """Upload `data` as `File:<filename>`, overwriting any existing file of that name
        (warnings are ignored so it replaces in place). `description` is the file page's
        wikitext, `comment` the upload-log summary. Requires a prior `login`."""
        if not self.logged_in:
            raise WikiError("not logged in; call login() before uploading")
        try:
            self.site.upload(
                file=io.BytesIO(data),
                filename=filename,
                description=description,
                comment=comment or None,
                ignore=True,  # overwrite an existing file of the same name (ignore warnings)
            )
        except (APIError, InsufficientPermission) as exc:
            raise WikiError(f"upload failed for {filename!r}: {exc}") from exc

    def delete(self, filename: str, reason: str = "") -> None:
        """Delete `File:<filename>`. Requires a prior `login` and the delete right (which a
        normal account usually lacks — the rejection surfaces as a `WikiError`)."""
        if not self.logged_in:
            raise WikiError("not logged in; call login() before deleting")
        page = self.site.pages[f"File:{filename}"]
        try:
            page.delete(reason=reason)
        except (ProtectedPageError, InsufficientPermission) as exc:
            raise WikiError(f"cannot delete File:{filename}: {exc}") from exc
        except APIError as exc:
            raise WikiError(f"delete failed for File:{filename}: {exc}") from exc

    def save(self, title: str, text: str, summary: str, minor: bool = False) -> SaveResult:
        """Replace the page's wikitext, returning the revisions the edit moved between.
        Requires a prior `login`; a protected page or API rejection raises `WikiError`."""
        if not self.logged_in:
            raise WikiError("not logged in; call login() before saving")
        page = self.site.pages[title]
        try:
            result = page.edit(text, summary=summary, minor=minor, bot=True)
        except (ProtectedPageError, InsufficientPermission) as exc:
            raise WikiError(f"cannot edit {title!r}: {exc}") from exc
        except APIError as exc:
            raise WikiError(f"save failed for {title!r}: {exc}") from exc
        return SaveResult(
            title=title,
            old_revid=result.get("oldrevid"),
            new_revid=result.get("newrevid"),
            no_change="nochange" in result,
        )
