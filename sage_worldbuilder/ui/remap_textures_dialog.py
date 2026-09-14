"""Remap Textures (WorldBuilder's 32929): give each texture the map uses another Terrain.ini
entry. WorldBuilder asks for one texture at a time; here they are all in one list."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

__all__ = ["RemapTexturesDialog"]


class RemapTexturesDialog(QDialog):
    def __init__(
        self, names: list[str], catalogue: list[str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remap Textures")
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Replace the Terrain.ini texture behind each of the map's textures. Leave a row empty "
            "to keep it. A replacement must be the same size, so every cell keeps its tile."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        holder = QWidget()
        form = QFormLayout(holder)
        completer = QCompleter(catalogue, self)
        completer.setCaseSensitivity(False)  # type: ignore[arg-type]
        self.fields: list[QLineEdit] = []
        for name in names:
            field = QLineEdit()
            field.setPlaceholderText("Keep")
            field.setCompleter(completer)
            form.addRow(name, field)
            self.fields.append(field)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(holder)
        layout.addWidget(area, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(420, 480)

    def replacements(self) -> dict[int, str]:
        """The new name for each texture the dialog was given a name for."""
        chosen = {}
        for index, field in enumerate(self.fields):
            name = field.text().strip()
            if name:
                chosen[index] = name
        return chosen
