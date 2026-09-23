"""Small wikitext file-name helpers shared by the wiki client and the image tooling. Kept
free of heavy (mwclient / PIL) imports so either side can use them."""

_FILE_NAMESPACES = ("file", "image")


def split_file_namespace(value: str) -> tuple[str, str]:
    """Split a wiki file reference into `(namespace, bare_name)`. `namespace` is the original
    `File:`/`Image:` text (verbatim, including the colon) when present, else `""`; both
    parts are stripped of surrounding whitespace. A value with no such prefix yields
    `("", value.strip())`, so callers get the bare name either way."""
    head, separator, rest = value.partition(":")
    if separator and head.strip().lower() in _FILE_NAMESPACES:
        return head.strip() + ":", rest.strip()
    return "", value.strip()
