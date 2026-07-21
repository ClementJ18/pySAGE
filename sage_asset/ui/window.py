"""The SAGE Asset window: build an asset.dat from an unpacked art tree, or combine a base
asset.dat with a mod overlay - the two operations `sage-asset build`/`combine` expose on the
command line. Both run on a background worker (see `sage_utils.widgets.run_worker`) so the
window stays responsive; the build reports the same 0-100/message progress its CLI and library
form share. Built on the shared sage_utils widgets (cards, the background Worker, the theme
toggle) so it looks and behaves like the other SAGE front ends."""

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sage_asset.assetdat import (
    AssetDat,
    AssetDatError,
    combine_asset_dats,
    parse_asset_dat_from_path,
    write_asset_dat_to_path,
)
from sage_asset.builder import build_asset_dat
from sage_utils.widgets import (
    CopyableLabel as QLabel,
)
from sage_utils.widgets import (
    ThemeToggle,
    Worker,
    card,
    resource_path,
    run_worker,
)

APP_NAME = "sage_asset"
APP_TITLE = "SAGE Asset"
ICON_FILE = "icon.ico"


class AssetWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        self.resize(760, 460)
        self._build_worker: Worker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel(APP_TITLE)
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        root.addWidget(title)

        root.addWidget(self._build_build_card())
        root.addWidget(self._build_combine_card())
        root.addStretch(1)

        footer = QHBoxLayout()
        credit = QLabel("asset.dat parsing based on work by Brechstange")
        credit.setObjectName("muted")
        footer.addWidget(credit)
        footer.addStretch(1)
        footer.addWidget(ThemeToggle())
        root.addLayout(footer)

    def _path_row(
        self, layout: QVBoxLayout, label: str, placeholder: str, on_browse: Callable[[], None]
    ) -> QLineEdit:
        """A labelled path field with a Browse button, appended to `layout`. Returns the field."""
        row = QHBoxLayout()
        caption = QLabel(label)
        caption.setMinimumWidth(100)
        row.addWidget(caption)
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        row.addWidget(field, 1)
        button = QPushButton("Browse…")
        button.clicked.connect(on_browse)
        row.addWidget(button)
        layout.addLayout(row)
        return field

    def _build_build_card(self) -> QWidget:
        frame, layout = card("Build")

        self.art_field = self._path_row(
            layout, "Art folder", "compiledtextures/ + w3d/", self._pick_art_dir
        )
        self.build_out_field = self._path_row(
            layout, "Output .dat", "where to write asset.dat", self._pick_build_out
        )

        self.build_progress = QProgressBar()
        self.build_progress.setRange(0, 100)
        layout.addWidget(self.build_progress)

        row = QHBoxLayout()
        self.build_status = QLabel("Pick an art folder and an output path.")
        self.build_status.setObjectName("muted")
        row.addWidget(self.build_status, 1)
        self.build_button = QPushButton("Build")
        self.build_button.setObjectName("primary")
        self.build_button.setToolTip(
            "Scan the art folder's compiledtextures/ and w3d/ and write the asset.dat it describes."
        )
        self.build_button.clicked.connect(self._run_build)
        row.addWidget(self.build_button)
        layout.addLayout(row)

        return frame

    def _build_combine_card(self) -> QWidget:
        frame, layout = card("Combine")

        self.base_field = self._path_row(
            layout, "Base .dat", "the base game's asset.dat", self._pick_base
        )
        self.overlay_field = self._path_row(
            layout, "Overlay .dat", "the mod's asset.dat", self._pick_overlay
        )
        self.combine_out_field = self._path_row(
            layout, "Output .dat", "where to write the combined asset.dat", self._pick_combine_out
        )

        row = QHBoxLayout()
        self.combine_status = QLabel("Pick a base, an overlay, and an output path.")
        self.combine_status.setObjectName("muted")
        row.addWidget(self.combine_status, 1)
        self.combine_button = QPushButton("Combine")
        self.combine_button.setObjectName("primary")
        self.combine_button.setToolTip(
            "Concatenate the base's files/references with the overlay's (base first, "
            "overlay after) and write the result."
        )
        self.combine_button.clicked.connect(self._run_combine)
        row.addWidget(self.combine_button)
        layout.addLayout(row)

        return frame

    def _pick_art_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose the art folder to build from")
        if chosen:
            self.art_field.setText(chosen)

    def _pick_build_out(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save asset.dat as", "asset.dat", "asset.dat (*.dat)"
        )
        if chosen:
            self.build_out_field.setText(chosen)

    def _pick_base(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choose the base asset.dat", "", "asset.dat (*.dat)"
        )
        if chosen:
            self.base_field.setText(chosen)

    def _pick_overlay(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choose the overlay asset.dat", "", "asset.dat (*.dat)"
        )
        if chosen:
            self.overlay_field.setText(chosen)

    def _pick_combine_out(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save combined asset.dat as", "asset.dat", "asset.dat (*.dat)"
        )
        if chosen:
            self.combine_out_field.setText(chosen)

    def _run_build(self) -> None:
        art_dir = self.art_field.text().strip()
        out_path = self.build_out_field.text().strip()
        if not art_dir or not Path(art_dir).is_dir():
            self.build_status.setText("Pick a valid art folder first.")
            return
        if not out_path:
            self.build_status.setText("Pick an output path first.")
            return

        self.build_button.setEnabled(False)
        self.build_progress.setValue(0)
        self.build_status.setText("Building…")

        def build() -> AssetDat:
            return self._build_result(art_dir)

        def on_done(ad: AssetDat) -> None:
            self._on_build_done(ad, out_path)

        self._build_worker = run_worker(self, build, on_done, self._on_build_failed)
        self._build_worker.progress.connect(self._on_build_progress)

    def _build_result(self, art_dir: str) -> AssetDat:
        """The scan itself, run on the worker thread. Split out from `_run_build` so it (and
        `_on_build_done` below) can be called directly in a test without going through the
        worker thread and Qt's queued signal delivery."""
        return build_asset_dat(Path(art_dir), progress=self._emit_build_progress)

    def _on_build_done(self, ad: AssetDat, out_path: str) -> None:
        # Runs on the GUI thread (a Qt slot): a write failure raised here would escape as an
        # unhandled slot exception and leave the button disabled, so route it to the status
        # label like a worker failure instead.
        try:
            write_asset_dat_to_path(ad, out_path)
        except (AssetDatError, OSError) as exc:
            self._on_build_failed(str(exc))
            return
        total_assets = sum(len(entry.assets) for entry in ad.files)
        self.build_button.setEnabled(True)
        self.build_progress.setValue(100)
        self.build_status.setText(
            f"Wrote {out_path}: {len(ad.files)} files, {total_assets} assets, "
            f"{len(ad.references)} references."
        )

    def _emit_build_progress(self, percent: int, message: str) -> None:
        """Called on the worker thread by `build_asset_dat`; re-emits through the worker's Qt
        signal (thread-safe) so the update crosses onto the GUI thread instead of touching
        widgets directly from off the main thread."""
        worker = self._build_worker
        if worker is not None:
            worker.progress.emit(f"{percent}:{message}")

    def _on_build_progress(self, payload: str) -> None:
        percent_str, _, message = payload.partition(":")
        self.build_progress.setValue(int(percent_str))
        self.build_status.setText(message)

    def _on_build_failed(self, message: str) -> None:
        self.build_button.setEnabled(True)
        self.build_status.setText(f"Build failed - {message}")

    def _run_combine(self) -> None:
        base_path = self.base_field.text().strip()
        overlay_path = self.overlay_field.text().strip()
        out_path = self.combine_out_field.text().strip()
        if not base_path or not Path(base_path).is_file():
            self.combine_status.setText("Pick a valid base .dat first.")
            return
        if not overlay_path or not Path(overlay_path).is_file():
            self.combine_status.setText("Pick a valid overlay .dat first.")
            return
        if not out_path:
            self.combine_status.setText("Pick an output path first.")
            return

        self.combine_button.setEnabled(False)
        self.combine_status.setText("Combining…")

        def combine() -> AssetDat:
            return self._combine_result(base_path, overlay_path)

        def on_done(combined: AssetDat) -> None:
            self._on_combine_done(combined, out_path)

        run_worker(self, combine, on_done, self._on_combine_failed)

    def _combine_result(self, base_path: str, overlay_path: str) -> AssetDat:
        """The parse + concatenate itself, run on the worker thread. Split out from
        `_run_combine` so it (and `_on_combine_done` below) can be called directly in a test
        without going through the worker thread and Qt's queued signal delivery."""
        base = parse_asset_dat_from_path(base_path)
        overlay = parse_asset_dat_from_path(overlay_path)
        return combine_asset_dats(base, overlay)

    def _on_combine_done(self, combined: AssetDat, out_path: str) -> None:
        # Same slot-side guard as `_on_build_done`: surface a write failure in the status
        # label rather than letting it escape the slot with the button still disabled.
        try:
            write_asset_dat_to_path(combined, out_path)
        except (AssetDatError, OSError) as exc:
            self._on_combine_failed(str(exc))
            return
        names = [entry.name.lower() for entry in combined.files]
        duplicate_names = len(names) - len(set(names))
        self.combine_button.setEnabled(True)
        self.combine_status.setText(
            f"Wrote {out_path}: {len(combined.files)} files, "
            f"{len(combined.references)} references, {duplicate_names} duplicate file names."
        )

    def _on_combine_failed(self, message: str) -> None:
        self.combine_button.setEnabled(True)
        self.combine_status.setText(f"Combine failed - {message}")
