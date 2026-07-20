# sage_wiki

A desktop tool that updates **Edain wiki** infoboxes from parsed game data: it maps an
object's stats onto a page's infobox fields, shows the diff for review, and applies it
through the MediaWiki action API.

Load one or more data sources, name a page, log in, generate the diff between its current
infobox and the object's stats, then apply. A category run automates that loop over every
page shared by one or more categories. Loading and network calls run on background threads
so the UI stays responsive.

## Running

Needs the `wiki` extra (mwclient, mwparserfromhell, PyQt6, pyBIG, keyring):

```sh
pip install "pysage-tools[wiki]"   # from a checkout: pip install -e ".[wiki]"
sage-wiki                     # or: python -m sage_wiki.app
```

Credentials are handled through `keyring`, with a login prompt each session.
