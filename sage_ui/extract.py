"""The Extract Images dialog: crop a command set's button icons out of textures.

Seeded with a unit's active command set buttons; the user loads image sources, previews
a button's cropped icon and saves one or all. An optional toggle overlays the crop on the
parchment portrait background. The Qt wrapper around the headless `sage_utils.textures`.
"""

from pathlib import Path

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from sage_utils.sources import load_saved_sources, save_sources
from sage_utils.textures import (
    TextureSource,
    composite_on_background,
    crop_mapped_image,
    default_background,
)
from sage_utils.views import flatten_button_images
from sage_utils.widgets import CopyableLabel as QLabel
from sage_utils.widgets import SourcesPanel, card, pil_to_pixmap, run_worker

# Image sources are remembered under their own app key, separate from the data sources.
TEXTURE_SOURCES_APP = "sage_ui_textures"


class ExtractImageDialog(QDialog):
    """Crop and save the button icons of one unit's command set. `entries` are the
    `command_button_images` dicts, flattened to one row per image; a button with no image
    is a row with `image` None (shown but not selectable)."""

    def __init__(self, unit_label: str, command_set_name: str, entries, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extract Images")
        self.resize(820, 560)
        self._entries = flatten_button_images(entries)
        self._source: TextureSource | None = None
        self._background = default_background()  # parchment behind portraits, if bundled

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        heading = QLabel(f"{unit_label}  ·  {command_set_name or 'icons'}")
        heading.setObjectName("objName")
        root.addWidget(heading)

        self.sources_panel = SourcesPanel(
            title="IMAGE SOURCES",
            expanded_hint="IMAGE SOURCES - texture folders / .big archives with the .dds files",
            item_label=lambda kind, path: f"[{kind}]  {Path(path).name}  -  {path}",
            list_max_height=120,
            show_status=True,
        )
        self.sources_panel.load_requested.connect(self._load_textures)
        self.status = self.sources_panel.status
        for kind, path in load_saved_sources(TEXTURE_SOURCES_APP):
            self.sources_panel.add_source(kind, path)
        root.addWidget(self.sources_panel)

        body = QHBoxLayout()
        body.setSpacing(12)

        list_card, list_layout = card("Buttons")
        self.button_list = QListWidget()
        self.button_list.currentRowChanged.connect(self._on_select)
        list_layout.addWidget(self.button_list)
        body.addWidget(list_card, 1)

        preview_card, preview_layout = card("Preview")
        self.preview = QLabel("Load an image source, then pick a button.")
        self.preview.setObjectName("muted")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(260, 260)
        self.preview.setWordWrap(True)
        preview_layout.addWidget(self.preview, 1)
        body.addWidget(preview_card, 1)

        root.addLayout(body, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.overlay_button = QPushButton("Overlay on background")
        self.overlay_button.setCheckable(True)
        self.overlay_button.setToolTip(
            "Center the image on the parchment portrait background"
            if self._background is not None
            else "No background image is bundled"
        )
        self.overlay_button.setEnabled(self._background is not None)
        self.overlay_button.toggled.connect(self._refresh_preview)
        actions.addWidget(self.overlay_button)
        actions.addStretch(1)
        self.save_one_button = QPushButton("Save image…")
        self.save_one_button.setToolTip("Save the selected button's icon as a PNG")
        self.save_one_button.clicked.connect(self._save_one)
        self.save_all_button = QPushButton("Save all…")
        self.save_all_button.setToolTip("Save every button's icon into a chosen folder")
        self.save_all_button.clicked.connect(self._save_all)
        self.save_all_button.setObjectName("primary")
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for button in (self.save_one_button, self.save_all_button, close):
            actions.addWidget(button)
        root.addLayout(actions)

        self._populate_buttons()
        self._update_actions()

    def _populate_buttons(self) -> None:
        """List every button; those with no icon are shown disabled (nothing to crop)."""
        for entry in self._entries:
            has_image = entry["image"] is not None
            label = entry["text"] if has_image else f"{entry['text']}  (no image)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            if not has_image:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.button_list.addItem(item)

    def _load_textures(self) -> None:
        sources = self.sources_panel.sources()
        if not sources:
            self.status.setText("Add an image folder or .big file first.")
            return
        save_sources(sources, TEXTURE_SOURCES_APP)
        self.sources_panel.load_button.setEnabled(False)
        self.status.setText(f"Indexing {len(sources)} image source(s)…")
        run_worker(
            self,
            lambda: TextureSource(sources),
            self._on_textures_loaded,
            self._on_textures_failed,
        )

    def _on_textures_loaded(self, source: TextureSource) -> None:
        self._source = source
        self.sources_panel.load_button.setEnabled(True)
        self.status.setText(f"Indexed {len(source)} texture(s). Pick a button to preview.")
        self.sources_panel.set_collapsed(True)
        self._update_actions()
        self._refresh_preview()

    def _on_textures_failed(self, message: str) -> None:
        self.sources_panel.load_button.setEnabled(True)
        self.status.setText(f"Could not index the image sources - {message}")

    def _current_entry(self) -> dict | None:
        item = self.button_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _on_select(self, _row: int) -> None:
        self._refresh_preview()
        self._update_actions()

    def _refresh_preview(self) -> None:
        entry = self._current_entry()
        if self._source is None:
            self._set_preview_message("Load an image source, then pick a button.")
            return
        if entry is None or entry["image"] is None:
            self._set_preview_message("Pick a button with an icon.")
            return
        picture = crop_mapped_image(self._source, entry["image"])
        if picture is None:
            texture = getattr(entry["image"], "Texture", "?")
            self._set_preview_message(f"Texture not found in the sources:\n{texture}")
            return
        picture = self._compose(picture)
        pixmap = pil_to_pixmap(picture)
        # Scale down to fit the preview box, but never upscale a small icon past 2x.
        target = min(self.preview.width(), self.preview.height(), picture.width * 2)
        if target > 0 and (pixmap.width() > target or pixmap.height() > target):
            pixmap = pixmap.scaled(
                target,
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.preview.setText("")
        self.preview.setPixmap(pixmap)

    def _compose(self, picture: Image.Image) -> Image.Image:
        """The crop overlaid on the parchment background when the overlay is on, else as-is.
        Honoured by both the preview and the save actions so a saved PNG matches the preview."""
        if self.overlay_button.isChecked() and self._background is not None:
            return composite_on_background(picture, self._background)
        return picture

    def _set_preview_message(self, text: str) -> None:
        self.preview.setPixmap(QPixmap())
        self.preview.setText(text)

    def _update_actions(self) -> None:
        entry = self._current_entry()
        loaded = self._source is not None
        self.save_one_button.setEnabled(loaded and entry is not None and entry["image"] is not None)
        self.save_all_button.setEnabled(loaded and any(e["image"] for e in self._entries))

    def _save_one(self) -> None:
        entry = self._current_entry()
        if self._source is None or entry is None or entry["image"] is None:
            return
        picture = crop_mapped_image(self._source, entry["image"])
        if picture is None:
            QMessageBox.warning(
                self, "Not found", f"The texture for “{entry['text']}” isn't in the sources."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save image", f"{entry['name']}.png", "PNG image (*.png)"
        )
        if not path:
            return
        self._compose(picture).save(path)
        self.status.setText(f"Saved {Path(path).name}.")

    def _save_all(self) -> None:
        if self._source is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Save all icons to a folder")
        if not folder:
            return
        saved, missing = 0, []
        for entry in self._entries:
            if entry["image"] is None:
                continue
            picture = crop_mapped_image(self._source, entry["image"])
            if picture is None:
                missing.append(entry["text"])
                continue
            self._compose(picture).save(str(Path(folder) / f"{entry['name']}.png"))
            saved += 1
        message = f"Saved {saved} icon(s) to {folder}."
        if missing:
            message += f"\n\n{len(missing)} texture(s) not found:\n" + "\n".join(missing)
        QMessageBox.information(self, "Save all", message)
        self.status.setText(f"Saved {saved} icon(s).")
