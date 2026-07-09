"""The IMAGES card: index texture sources, preview an object's portrait and button
icons beside the wiki's current files, and upload the rendered PNGs."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sage_utils.sources import save_sources
from sage_utils.textures import (
    TextureSource,
    ability_overlay,
)
from sage_utils.widgets import (
    SourcesPanel,
    card,
)
from sage_wiki.diff import (
    resolve_object,
)
from sage_wiki.images import (
    command_set_icon_rows,
    filename_from_value,
    icon_filename,
    object_command_icon_rows,
    portrait_filename,
    render_icon_png,
    render_portrait_png,
)
from sage_wiki.infobox import parse_infobox
from sage_wiki.meta import TEXTURE_SOURCES_APP
from sage_wiki.pagegen import (
    button_ability_block,
    button_overlay_kind,
)
from sage_wiki.wiki import WikiError


class ImagesCardMixin:
    def _build_images_card(self) -> QWidget:
        # Keyed off the page/object the diff workflow names, with its own image sources.
        frame, layout = card()
        self.images_frame = frame
        self.images_toggle = QPushButton()
        self.images_toggle.setObjectName("sectionHeader")
        self.images_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.images_toggle.clicked.connect(self._toggle_images)
        layout.addWidget(self.images_toggle)

        self.images_body = QWidget()
        body = QVBoxLayout(self.images_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        note = QLabel(
            "Crop a unit portrait from the image sources below and upload it as <object>.png "
            "- then copy the file name into the infobox image yourself. Defaults to the Page "
            "and object above; type an object below to preview any other one (e.g. another "
            "form of a complex hero)."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        body.addWidget(note)

        self.image_sources_panel = SourcesPanel(
            title="IMAGE SOURCES",
            expanded_hint="IMAGE SOURCES - texture folders / .big archives with the .dds files",
            item_label=lambda kind, path: f"[{kind}]  {Path(path).name}  -  {path}",
            list_max_height=120,
        )
        self.image_sources_panel.load_requested.connect(self._load_textures)
        body.addWidget(self.image_sources_panel)

        # Optional: a specific object whose portrait (and button icons) to show, overriding the
        # page's resolved object - handy for a complex hero's other form objects (the fell
        # beast, ring hunter, …). Enter previews it.
        self.portrait_object_search = QLineEdit()
        self.portrait_object_search.setPlaceholderText(
            "(optional) object to preview - defaults to the page's"
        )
        self.portrait_object_search.setEnabled(False)
        self.portrait_object_search.returnPressed.connect(self._preview_portrait)
        body.addWidget(self.portrait_object_search)

        # Side-by-side compare: the page's current wiki image next to the portrait cropped
        # from the sources. The current image comes from the wiki, independent of textures.
        previews = QHBoxLayout()
        previews.setSpacing(8)
        self.current_image_preview = self._build_compare_preview(
            previews, "Current (wiki)", "The page's current infobox image appears here."
        )
        self.image_preview = self._build_compare_preview(
            previews, "Generated", "Load image sources, then Preview the portrait."
        )
        body.addLayout(previews)

        row = QHBoxLayout()
        self.image_status = QLabel("")
        self.image_status.setObjectName("muted")
        # Wrap long status text (esp. wiki upload errors) instead of letting it stretch the
        # whole column wide.
        self.image_status.setWordWrap(True)
        row.addWidget(self.image_status, 1)
        self.image_preview_button = QPushButton("Preview")
        self.image_preview_button.setEnabled(False)  # enabled once image sources load
        self.image_preview_button.clicked.connect(self._preview_portrait)
        row.addWidget(self.image_preview_button)
        self.image_upload_button = QPushButton("Upload")
        self.image_upload_button.setObjectName("primary")
        self.image_upload_button.setEnabled(False)
        self.image_upload_button.clicked.connect(self._upload_portrait)
        row.addWidget(self.image_upload_button)
        body.addLayout(row)

        # The uploaded portrait's file name, surfaced (read-only, selectable) to copy into
        # the infobox rather than rewriting the page.
        self.image_name_field = QLineEdit()
        self.image_name_field.setReadOnly(True)
        self.image_name_field.setPlaceholderText("Uploaded portrait file name appears here.")
        body.addWidget(self.image_name_field)

        icons_note = QLabel(
            "Button icons list automatically for the loaded page's object. Upload any of "
            "them individually, or use Ability to copy its {{Ability}} template. Each shows "
            "its <name>.png to copy where you need it."
        )
        icons_note.setObjectName("muted")
        icons_note.setWordWrap(True)
        body.addWidget(icons_note)

        # Type a command set to list it directly instead of the object's own (Enter to apply).
        self.commandset_search = QLineEdit()
        self.commandset_search.setPlaceholderText(
            "(optional) command set to list - defaults to the object's"
        )
        self.commandset_search.setEnabled(False)
        self.commandset_search.returnPressed.connect(self._list_button_icons)
        body.addWidget(self.commandset_search)

        self.icons_area = QScrollArea()
        self.icons_area.setWidgetResizable(True)
        self.icons_area.setMinimumHeight(160)
        self.icons_area.setMaximumHeight(320)
        container = QWidget()
        self.icons_layout = QVBoxLayout(container)
        self.icons_layout.setContentsMargins(4, 4, 4, 4)
        self.icons_layout.setSpacing(4)
        self.icons_layout.addStretch(1)
        self.icons_area.setWidget(container)
        body.addWidget(self.icons_area)

        layout.addWidget(self.images_body)
        self.images_body.setVisible(False)  # collapsed by default
        frame.setMaximumHeight(frame.sizeHint().height())  # start shrunk in the splitter
        self._update_images_header()
        return frame

    def _build_compare_preview(self, row: QHBoxLayout, caption: str, placeholder: str) -> QLabel:
        """Add a captioned image preview to `row`, returning its image QLabel (used for the
        two side-by-side previews so both share one slot with a heading)."""
        column = QVBoxLayout()
        column.setSpacing(2)
        heading = QLabel(caption)
        heading.setObjectName("muted")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(heading)
        preview = QLabel(placeholder)
        preview.setObjectName("muted")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumHeight(180)
        preview.setWordWrap(True)
        column.addWidget(preview, 1)
        row.addLayout(column, 1)
        return preview

    def _toggle_images(self) -> None:
        self._set_card_collapsed(
            self.images_frame,
            self.images_body,
            self.images_body.isVisible(),
            self._update_images_header,
        )

    def _expand_images(self) -> None:
        """Reveal the images card (used by the auto-load paths) through the collapse helper so
        its frame cap is lifted and the splitter handle moves."""
        if not self.images_body.isVisible():
            self._set_card_collapsed(
                self.images_frame, self.images_body, False, self._update_images_header
            )

    def _update_images_header(self) -> None:
        arrow = "▾" if self.images_body.isVisible() else "▸"
        self.images_toggle.setText(f"{arrow}  IMAGES")

    def _load_textures(self) -> None:
        sources = self.image_sources_panel.sources()
        if not sources:
            self.image_status.setText("Add an image folder or .big file first.")
            return
        save_sources(sources, TEXTURE_SOURCES_APP)
        self.image_sources_panel.load_button.setEnabled(False)
        self.image_status.setText(f"Indexing {len(sources)} image source(s)…")
        self._run(
            lambda: TextureSource(sources),
            self._on_textures_loaded,
            self._on_textures_failed,
        )

    def _on_textures_loaded(self, source: TextureSource) -> None:
        self._texture_source = source
        self.image_sources_panel.load_button.setEnabled(True)
        self.image_sources_panel.set_collapsed(True)
        self.image_preview_button.setEnabled(True)
        self.image_upload_button.setEnabled(True)
        self.image_status.setText(f"Indexed {len(source)} texture(s). Preview or upload.")
        # Fill the card for whatever object is already in play (it may have loaded first).
        self._images_loaded_for = None
        self._auto_load_images(self._current_object())

    def _on_textures_failed(self, message: str) -> None:
        self.image_sources_panel.load_button.setEnabled(True)
        self.image_status.setText(f"Could not index the image sources - {message}")

    def _portrait_object(self, game):
        """The object whose portrait to use - the images card's own object box, else the
        Page-and-object override or the page-generation object, all without a fetch, else the
        page's infobox object id. Raises `WikiError` with a usable message."""
        for box in (self.portrait_object_search, self.object_search, self.pagegen_object):
            name = box.text().strip()
            if name:
                obj = game.objects.get(name)
                if obj is None:
                    raise WikiError(f"object “{name}” is not loaded")
                return obj
        title = self.page_field.text().strip()
        if not title:
            raise WikiError("enter a page title or an object name")
        infobox = parse_infobox(self.client.fetch_wikitext(title))
        if infobox is None:
            raise WikiError(f"no infobox found on “{title}”")
        obj = resolve_object(infobox, game)
        if obj is None:
            raise WikiError(f"could not resolve an object for “{title}”")
        return obj

    def _current_object(self):
        """The object the workflow currently names (the override box, else the page-generation
        box), or None. Used to auto-fill images once textures load."""
        if self.game is None:
            return None
        name = self.object_search.text().strip() or self.pagegen_object.text().strip()
        return self.game.objects.get(name) if name else None

    def _auto_load_images(self, obj) -> None:
        """Fill the portrait preview and button icons for `obj` when textures are loaded,
        saving the manual Preview/List clicks. A no-op when no textures are indexed, there is
        no object, or the card already shows this one."""
        if self._texture_source is None or obj is None:
            return
        if obj.name == self._images_loaded_for:
            return
        self._images_loaded_for = obj.name
        self._expand_images()  # reveal the card
        self._start_portrait_preview(obj)
        self._start_icon_list(obj)

    def _preview_portrait(self) -> None:
        self._start_portrait_preview()

    def _start_portrait_preview(self, obj=None) -> None:
        if self.game is None:
            self.image_status.setText("Load a data source first.")
            return
        if self._texture_source is None:
            self.image_status.setText("Load image sources first.")
            return
        game, source = self.game, self._texture_source
        background = self._portrait_background
        self.image_preview_button.setEnabled(False)
        self.image_status.setText("Resolving portrait…")

        def task():
            # An explicit object (an auto-load) is used as-is; otherwise resolve from the
            # override box or the page, which may fetch it.
            target = obj if obj is not None else self._portrait_object(game)
            png = render_portrait_png(source, target, background)
            if png is None:
                raise WikiError(f"no portrait found for {target.name} in the image sources")
            return target.name, png

        self._run(task, self._on_portrait_preview, self._on_portrait_failed)

    def _on_portrait_preview(self, result) -> None:
        name, png = result
        self.image_preview_button.setEnabled(True)
        pixmap = QPixmap()
        if not pixmap.loadFromData(png):
            self.image_status.setText("Could not decode the cropped portrait.")
            return
        target = min(self.image_preview.width(), self.image_preview.height())
        if target > 0 and (pixmap.width() > target or pixmap.height() > target):
            pixmap = pixmap.scaled(
                target,
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.image_preview.setText("")
        self.image_preview.setPixmap(pixmap)
        # Surface the prospective file name so it can be copied even before upload.
        self.image_name_field.setText(f"{name}.png")
        self.image_status.setText(f"Preview of {name}.png - review, then upload.")

    def _upload_portrait(self) -> None:
        if self.game is None:
            self.image_status.setText("Load a data source first.")
            return
        if self._texture_source is None:
            self.image_status.setText("Load image sources first.")
            return
        if not self.client.logged_in:
            self.image_status.setText("Log in first to upload images.")
            return
        # Resolve as Preview does and upload; the page text is left untouched, the file name
        # surfaced below for the editor to copy in.
        game, source, background = self.game, self._texture_source, self._portrait_background
        self.image_upload_button.setEnabled(False)
        self.image_status.setText("Resolving portrait…")

        def task():
            obj = self._portrait_object(game)
            png = render_portrait_png(source, obj, background)
            if png is None:
                raise WikiError(f"no portrait found for {obj.name} in the image sources")
            filename = portrait_filename(obj)
            self.client.upload(
                png,
                filename,
                description=f"{obj.name} portrait, uploaded from game data by sage_wiki.",
                comment=f"Upload {obj.name} portrait from game data",
            )
            return filename

        self._run(task, self._on_portrait_uploaded, self._on_portrait_failed)

    def _on_portrait_uploaded(self, filename: str) -> None:
        self.image_upload_button.setEnabled(True)
        self.image_name_field.setText(filename)
        self.image_status.setText(f"Uploaded {filename} - copy its name into the infobox image.")

    def _on_portrait_failed(self, message: str) -> None:
        self.image_preview_button.setEnabled(self._texture_source is not None)
        self.image_upload_button.setEnabled(self._texture_source is not None)
        self.image_status.setText(f"Portrait failed - {message}")

    def _load_current_image(self, image_value: str | None) -> None:
        """Show the page's current infobox image (from `image_value`) in the Current preview,
        fetched from the wiki for comparison - independent of the texture sources."""
        filename = filename_from_value(image_value)
        if filename is None:
            self.current_image_preview.setPixmap(QPixmap())  # drop any previous page's image
            self.current_image_preview.setText("This page's infobox names no image.")
            return
        self._expand_images()  # reveal the card
        self.current_image_preview.setPixmap(QPixmap())
        self.current_image_preview.setText(f"Loading {filename}…")
        self._run(
            lambda: (filename, self.client.fetch_image(filename)),
            self._on_current_image,
            self._on_current_image_failed,
        )

    def _on_current_image(self, result) -> None:
        filename, data = result
        if not data:
            self.current_image_preview.setPixmap(QPixmap())
            self.current_image_preview.setText(f"{filename} is not on the wiki yet.")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self.current_image_preview.setPixmap(QPixmap())
            self.current_image_preview.setText(f"Could not decode {filename}.")
            return
        target = min(self.current_image_preview.width(), self.current_image_preview.height())
        if target > 0 and (pixmap.width() > target or pixmap.height() > target):
            pixmap = pixmap.scaled(
                target,
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.current_image_preview.setText("")
        self.current_image_preview.setPixmap(pixmap)

    def _on_current_image_failed(self, message: str) -> None:
        self.current_image_preview.setPixmap(QPixmap())
        self.current_image_preview.setText(f"Current image failed - {message}")

    def _list_button_icons(self) -> None:
        self._start_icon_list()

    def _start_icon_list(self, obj=None) -> None:
        if self.game is None:
            self.image_status.setText("Load a data source first.")
            return
        if self._texture_source is None:
            self.image_status.setText("Load image sources first.")
            return
        game, source = self.game, self._texture_source
        # An auto-load lists the object's own command set; typing one in the search box and
        # pressing Enter lists that set instead.
        command_set_name = "" if obj is not None else self.commandset_search.text().strip()
        self.image_status.setText("Resolving button icons…")

        def task():
            # A named command set is listed directly; otherwise the one the object displays,
            # reporting its name so the searchbox can be filled with it.
            if command_set_name:
                command_set = game.commandsets.get(command_set_name)
                if command_set is None:
                    raise WikiError(f"command set “{command_set_name}” is not loaded")
                set_name, source_rows = command_set_name, command_set_icon_rows(game, command_set)
            else:
                target = obj if obj is not None else self._portrait_object(game)
                set_name, source_rows = object_command_icon_rows(game, target)
            # Crop every icon up front (None when unresolvable); upload reuses these bytes.
            # Every icon is framed with its active/passive overlay so the frame is in both the
            # preview and the uploaded file.
            rows = []
            for r in source_rows:
                button = game.commandbuttons.get(r["button"])
                overlay = ability_overlay(button_overlay_kind(button))
                rows.append(
                    {
                        "name": r["name"],
                        "text": r["text"],
                        "button": r["button"],
                        "png": render_icon_png(source, r["image"], overlay),
                    }
                )
            return set_name, rows

        self._run(task, self._on_button_icons, self._on_button_icons_failed)

    def _on_button_icons(self, result) -> None:
        set_name, rows = result
        if set_name:  # reflect the command set that was listed (esp. the auto-resolved one)
            self.commandset_search.setText(set_name)
        self._clear_icon_rows()
        croppable = 0
        for row in rows:
            self._add_icon_row(row)
            croppable += row["png"] is not None
        label = set_name or "object"
        self.image_status.setText(
            f"{label}: {croppable} of {len(rows)} button icon(s) ready to upload."
            if rows
            else f"{label}: no command-set buttons to extract."
        )

    def _on_button_icons_failed(self, message: str) -> None:
        self.image_status.setText(f"Button icons failed - {message}")

    def _clear_icon_rows(self) -> None:
        """Remove every icon row, leaving the trailing stretch in place."""
        while self.icons_layout.count() > 1:
            item = self.icons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_icon_row(self, row: dict) -> None:
        """One button-icon row: thumbnail, label, copyable name, Upload and Ability."""
        wrap = QWidget()
        line = QHBoxLayout(wrap)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)

        png = row["png"]
        thumb = QLabel()
        thumb.setFixedSize(28, 28)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if png is not None:
            pixmap = QPixmap()
            if pixmap.loadFromData(png):
                thumb.setPixmap(
                    pixmap.scaled(
                        28,
                        28,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        line.addWidget(thumb)

        label = QLabel(row["text"])
        label.setWordWrap(True)
        line.addWidget(label, 1)

        # The destination file name, read-only but selectable.
        name_field = QLineEdit(icon_filename(row["name"]))
        name_field.setReadOnly(True)
        name_field.setMinimumWidth(150)
        line.addWidget(name_field, 1)

        upload = QPushButton("Upload")
        if png is None:
            upload.setEnabled(False)
            upload.setToolTip("This button has no icon, or its texture isn't in the sources.")
        else:
            upload.clicked.connect(
                lambda _=False, r=row, b=upload: self._upload_icon(r["name"], r["png"], b)
            )
        line.addWidget(upload)

        # Scaffold this button's {{Ability}} template (with its icon filename pre-filled)
        # and copy it to the clipboard, ready to paste into the page.
        ability = QPushButton("Ability")
        ability.setToolTip("Copy this button's {{Ability}} template to the clipboard.")
        ability.clicked.connect(lambda _=False, r=row: self._copy_ability(r))
        line.addWidget(ability)

        self.icons_layout.insertWidget(self.icons_layout.count() - 1, wrap)  # before the stretch

    def _copy_ability(self, row: dict) -> None:
        """Generate the `{{Ability}}` template for a row's command button and put it on the
        clipboard. Reports when the button isn't an ability (nothing to scaffold)."""
        if self.game is None:
            self.image_status.setText("Load a data source first.")
            return
        block = button_ability_block(self.game, row["button"], icon_filename(row["name"]))
        if not block:
            self.image_status.setText(f"{row['text']}: no ability template to generate.")
            return
        QApplication.clipboard().setText(block)
        self.image_status.setText(f"Copied {row['text']} ability template to the clipboard.")

    def _upload_icon(self, name: str, png: bytes, button: QPushButton) -> None:
        if not self.client.logged_in:
            self.image_status.setText("Log in first to upload images.")
            return
        filename = icon_filename(name)
        button.setEnabled(False)
        self.image_status.setText(f"Uploading {filename}…")

        def task():
            self.client.upload(
                png,
                filename,
                description=f"{name} icon, uploaded from game data by sage_wiki.",
                comment=f"Upload {name} icon from game data",
            )
            return filename

        self._run(
            task,
            lambda fn, b=button: self._on_icon_uploaded(fn, b),
            lambda message, b=button: self._on_icon_upload_failed(message, b),
        )

    def _on_icon_uploaded(self, filename: str, button: QPushButton) -> None:
        button.setText("Uploaded")
        button.setEnabled(False)
        self.image_status.setText(f"Uploaded {filename} - copy its name from the field.")

    def _on_icon_upload_failed(self, message: str, button: QPushButton) -> None:
        button.setEnabled(True)
        self.image_status.setText(f"Icon upload failed - {message}")
