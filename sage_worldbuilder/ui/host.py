"""What the editor's panels need from the window around them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from sage_worldbuilder.commands import Command
from sage_worldbuilder.document import MapDocument

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = ["PanelHost"]


class PanelHost(Protocol):
    @property
    def document(self) -> MapDocument | None: ...

    @property
    def game(self) -> Game | None: ...

    def execute(self, command: Command) -> None: ...
