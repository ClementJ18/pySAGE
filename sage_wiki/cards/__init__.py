"""The Edain Wiki Assistant's feature cards, one mixin module per card/workflow, composed
into the `WikiUpdater` window by `sage_wiki.app`. Each mixin builds its own widgets and
owns their handlers; shared state (the loaded game, the wiki client, the status bar and
worker plumbing) lives on the window."""
