"""View a .w3d model in a PyQt6/OpenGL window, with a sidebar of per-mesh visibility checkboxes,
a lighting-preset picker, and - when the model resolves a skeleton and carries (or is given)
animation chunks - an animation picker with play/pause and a scrub slider. A miniature of what
finalBIGv2's W3D tab would become built on top of `sage_w3d.render`. Needs the `w3d-view` extra
(`pip install "pysage-tools[w3d-view]"`).

Usage:
    python view_model.py <model.w3d> [--art DIR ...] [--big ARCHIVE.big] [--anim FILE ...]

--art directories (default: the model's own directory) resolve the skeleton an HLOD names and
any textures a material references. --big points at a .big archive to resolve them from
instead (or as well - it is tried first, falling back to --art); this is also a worked example
of the `AssetResolver` protocol: swap in any lookup a real asset pipeline needs. --anim names
one or more standalone `.w3d` files carrying animation chunks to add to the picker, alongside
any the model itself carries.

--smoke constructs the window and quits immediately without showing it - used by this
package's own verification, not something an interactive user needs.
"""

import argparse
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from sage_w3d import W3DFile, parse_w3d, parse_w3d_from_path
from sage_w3d.render.pose import AnimationSource, PoseEvaluator
from sage_w3d.render.scene import AssetResolver, DirectoryResolver, Scene, build_scene
from sage_w3d.render.viewport import LIGHTING_PRESETS, PlaybackController, W3DViewport

_TEXTURE_EXTENSIONS = (".dds", ".tga")


class BigArchiveResolver:
    """An `AssetResolver` reading hierarchies/textures out of a .big archive (via pyBIG),
    falling back to `fallback` for anything the archive doesn't have. A real game install
    ships its assets packed this way, not as loose files - this is the worked example of the
    protocol's extension point `sage_w3d/README.md` points at."""

    def __init__(self, archive_path: str, fallback: AssetResolver | None = None) -> None:
        try:
            import pyBIG  # noqa: PLC0415 - lazy: needs the `ui` extra
        except ImportError as exc:
            raise ImportError(
                'reading a .big archive needs pyBIG - install the "ui" extra: '
                'pip install "pysage-tools[ui]"'
            ) from exc

        self._archive = pyBIG.InDiskArchive(archive_path)
        self._fallback = fallback
        self._by_stem: dict[str, list[str]] = {}
        for name in self._archive.file_list():
            stem = Path(name.replace("\\", "/")).stem.lower()
            self._by_stem.setdefault(stem, []).append(name)

    def find_hierarchy(self, name: str) -> W3DFile | None:
        stem = Path(name).stem.lower()
        for entry in self._by_stem.get(stem, ()):
            if entry.lower().endswith(".w3d"):
                return parse_w3d(self._archive.read_file(entry))
        return self._fallback.find_hierarchy(name) if self._fallback else None

    def find_texture(self, name: str) -> bytes | None:
        stem = Path(name).stem.lower()
        for ext in _TEXTURE_EXTENSIONS:
            for entry in self._by_stem.get(stem, ()):
                if entry.lower().endswith(ext):
                    return self._archive.read_file(entry)
        return self._fallback.find_texture(name) if self._fallback else None


class MainWindow(QMainWindow):
    def __init__(
        self,
        scene: Scene,
        textures: dict[str, bytes],
        title: str,
        animation_sources: list[AnimationSource],
    ) -> None:
        super().__init__()
        self.setWindowTitle(title)
        self.viewport = W3DViewport(scene, textures)
        self._controller = PlaybackController(self.viewport, parent=self)
        self._controller.frame_changed.connect(self._on_frame_changed)
        self._evaluators = (
            [PoseEvaluator(scene.hierarchy, source) for source in animation_sources]
            if scene.hierarchy is not None
            else []
        )

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(QLabel("<b>Meshes</b>"))
        for mesh in scene.meshes:
            checkbox = QCheckBox(mesh.name)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(
                lambda state, n=mesh.name: self.viewport.set_mesh_visible(n, state != 0)
            )
            sidebar_layout.addWidget(checkbox)

        sidebar_layout.addWidget(QLabel("<b>Lighting</b>"))
        lighting_combo = QComboBox()
        lighting_combo.addItems(sorted(LIGHTING_PRESETS))
        lighting_combo.currentTextChanged.connect(self.viewport.set_lighting)
        sidebar_layout.addWidget(lighting_combo)

        sidebar_layout.addWidget(QLabel("<b>Animation</b>"))
        self._anim_combo = QComboBox()
        self._anim_combo.addItem("Rest pose")
        for evaluator in self._evaluators:
            label = f"{evaluator.name} ({evaluator.num_frames} @ {evaluator.frame_rate:g} fps)"
            self._anim_combo.addItem(label)
        self._anim_combo.currentIndexChanged.connect(self._select_animation)
        sidebar_layout.addWidget(self._anim_combo)

        self._play_button = QPushButton("Play")
        self._play_button.clicked.connect(self._toggle_playback)
        sidebar_layout.addWidget(self._play_button)

        self._frame_slider = QSlider(Qt.Orientation.Horizontal)
        self._frame_slider.valueChanged.connect(self._scrub)
        sidebar_layout.addWidget(self._frame_slider)

        animatable = bool(self._evaluators)
        self._anim_combo.setEnabled(animatable)
        self._play_button.setEnabled(animatable)
        self._frame_slider.setEnabled(animatable)

        sidebar_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(sidebar)
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(250)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self.viewport, stretch=1)
        layout.addWidget(scroll)
        self.setCentralWidget(central)
        self.resize(1000, 700)

    def _select_animation(self, index: int) -> None:
        """`index` 0 is the "Rest pose" entry (restores the static pose); `index - 1` otherwise
        indexes `self._evaluators`, in the same order they were added to the combo."""
        if index <= 0 or index - 1 >= len(self._evaluators):
            self._controller.set_evaluator(None)
        else:
            self._controller.set_evaluator(self._evaluators[index - 1])
            self._frame_slider.setMaximum(max(self._evaluators[index - 1].num_frames - 1, 0))
        self._play_button.setText("Play")

    def _toggle_playback(self) -> None:
        self._controller.toggle()
        self._play_button.setText("Pause" if self._controller.playing else "Play")

    def _scrub(self, value: int) -> None:
        if self._controller.playing:
            return
        self._controller.set_frame(float(value))

    def _on_frame_changed(self, frame: float) -> None:
        # Blocked so the slider's own valueChanged (-> _scrub) doesn't fire back into the
        # controller it is only meant to be reflecting here.
        self._frame_slider.blockSignals(True)
        self._frame_slider.setValue(round(frame))
        self._frame_slider.blockSignals(False)


def _build_resolver(model_path: Path, art_dirs: list[Path], big_path: str | None) -> AssetResolver:
    fallback = DirectoryResolver(*(art_dirs or [model_path.parent]))
    return BigArchiveResolver(big_path, fallback=fallback) if big_path else fallback


def _animation_sources(model: W3DFile, anim_paths: list[Path]) -> list[AnimationSource]:
    """The model's own `animations + compressed_animations`, plus every `--anim` file's (each
    parsed separately) - `sage_w3d.__main__`'s `view --anim` builds the same shape from a single
    optional file; this example takes `nargs="*"` since a sidebar picker has room for more than
    one standalone animation to choose from."""
    sources: list[AnimationSource] = [*model.animations, *model.compressed_animations]
    for anim_path in anim_paths:
        anim_model = parse_w3d_from_path(anim_path)
        sources += [*anim_model.animations, *anim_model.compressed_animations]
    return sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--art", type=Path, nargs="*", default=[])
    parser.add_argument("--big", default=None, help="a .big archive to resolve assets from")
    parser.add_argument(
        "--anim", type=Path, nargs="*", default=[], help="standalone animation .w3d file(s)"
    )
    parser.add_argument(
        "--smoke", action="store_true", help="construct the window then quit immediately"
    )
    args = parser.parse_args(argv)

    model = parse_w3d_from_path(args.model)
    resolver = _build_resolver(args.model, args.art, args.big)
    scene = build_scene(model, resolver)
    animation_sources = _animation_sources(model, args.anim)

    textures: dict[str, bytes] = {}
    for mesh in scene.meshes:
        if mesh.texture is not None and mesh.texture not in textures:
            data = resolver.find_texture(mesh.texture)
            if data is not None:
                textures[mesh.texture] = data

    app = QApplication(sys.argv[:1])
    window = MainWindow(scene, textures, args.model.name, animation_sources)
    window.show()

    if args.smoke:
        QTimer.singleShot(0, app.quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
