"""Qt-level tests for the sage_asset UI: the Build and Combine cards' key widgets exist, and
the combine handler's result/status logic runs correctly end to end. Headless via the Qt
'offscreen' platform, so no display is needed; marked `full` (peripheral package, like the
other sage_utils/sage_ui suites)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [asset-ui] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_asset.assetdat import AssetDat, FileEntry, write_asset_dat_to_path  # noqa: E402
from sage_asset.ui.window import AssetWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    return AssetWindow()


def test_build_card_has_its_key_widgets(window):
    assert window.art_field.placeholderText()
    assert window.build_out_field.placeholderText()
    assert window.build_progress.minimum() == 0
    assert window.build_progress.maximum() == 100
    assert window.build_button.text() == "Build"


def test_combine_card_has_its_key_widgets(window):
    assert window.base_field.placeholderText()
    assert window.overlay_field.placeholderText()
    assert window.combine_out_field.placeholderText()
    assert window.combine_button.text() == "Combine"


def test_combine_writes_result_and_reports_duplicate_count(window, tmp_path):
    # Overlay collides with base on "a.w3d" - the combined file keeps both (a duplicate name),
    # which is the mechanism this UI exists to drive, not a bug to hide.
    base = AssetDat(version=0x102, files=[FileEntry(name="a.w3d", file_time=1, assets=[])])
    overlay = AssetDat(version=0x102, files=[FileEntry(name="a.w3d", file_time=2, assets=[])])
    base_path = tmp_path / "base.dat"
    overlay_path = tmp_path / "overlay.dat"
    out_path = tmp_path / "combined.dat"
    write_asset_dat_to_path(base, base_path)
    write_asset_dat_to_path(overlay, overlay_path)

    # The worker-thread result-handling is called directly, bypassing run_worker's background
    # QThread and Qt's cross-thread signal delivery - exercising the same code the Combine
    # button drives without needing to pump the event loop for an async result.
    combined = window._combine_result(str(base_path), str(overlay_path))
    window._on_combine_done(combined, str(out_path))

    assert out_path.is_file()
    assert len(combined.files) == 2
    assert "2 files" in window.combine_status.text()
    assert "1 duplicate file names" in window.combine_status.text()
    assert window.combine_button.isEnabled()


def test_combine_failure_surfaces_in_status_label(window):
    window._on_combine_failed("boom")

    assert "Combine failed" in window.combine_status.text()
    assert "boom" in window.combine_status.text()
    assert window.combine_button.isEnabled()


def test_unwritable_output_surfaces_in_status_label_not_a_slot_exception(window, tmp_path):
    # The write runs on the GUI thread inside the done-slot; a bad output path must land in
    # the status label with the button re-enabled, not escape the slot as an exception.
    combined = AssetDat(version=0x102, files=[FileEntry(name="a.w3d", file_time=1, assets=[])])
    bad_out = tmp_path / "no-such-dir" / "combined.dat"

    window._on_combine_done(combined, str(bad_out))

    assert "Combine failed" in window.combine_status.text()
    assert window.combine_button.isEnabled()

    window._on_build_done(combined, str(bad_out))

    assert "Build failed" in window.build_status.text()
    assert window.build_button.isEnabled()


def test_run_build_rejects_a_missing_art_folder(window, tmp_path):
    window.art_field.setText(str(tmp_path / "does-not-exist"))
    window.build_out_field.setText(str(tmp_path / "out.dat"))

    window._run_build()

    assert "valid art folder" in window.build_status.text()


def test_run_combine_rejects_a_missing_base_file(window, tmp_path):
    window.base_field.setText(str(tmp_path / "does-not-exist.dat"))
    window.overlay_field.setText(str(tmp_path / "does-not-exist.dat"))
    window.combine_out_field.setText(str(tmp_path / "out.dat"))

    window._run_combine()

    assert "valid base" in window.combine_status.text()
