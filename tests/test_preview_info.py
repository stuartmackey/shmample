import struct
import wave

import pytest
from textual_plotext import PlotextPlot

from shmample import sample_store
from shmample.app import ShmampleApp
from shmample.device import human_bytes
from shmample.tag_store import auto_assign_tag
from shmample.widgets import preview_info as preview_info_module
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.preview_info import PreviewInfo, _format_sample_rate


@pytest.fixture
def samples_dir(tmp_path):
    wav_path = tmp_path / "kick.wav"
    with wave.open(str(wav_path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"".join(struct.pack("<h", 1000) for _ in range(4000)))
    drums = tmp_path / "Drums"
    drums.mkdir()
    (drums / "snare.wav").write_bytes(b"")  # folder needs a wav to still be shown at all
    return tmp_path


def test_format_sample_rate_drops_trailing_zeros():
    assert _format_sample_rate(44100) == "44.1kHz"
    assert _format_sample_rate(48000) == "48kHz"
    assert _format_sample_rate(22050) == "22.05kHz"
    assert _format_sample_rate(8000) == "8kHz"


def _status_text(preview: PreviewInfo) -> str:
    return str(preview.query_one("#preview-date").render())


def _format_text(preview: PreviewInfo) -> str:
    return str(preview.query_one("#preview-format").render())


async def _expanded_root(browser: FileBrowser, pilot):
    """The single configured samples_dir's own root node, expanded and
    loaded - each configured directory is now its own root-level node
    (11-sample-paths.md), one level deeper than kick.wav/Drums used to
    sit when there was only ever a single samples_directory."""
    root_node = browser.root.children[0]
    root_node.expand()
    await pilot.pause()
    return root_node


def _node(root_node, name):
    return next(n for n in root_node.children if name in str(n.label))


async def test_highlighting_a_file_shows_its_name_date_duration_and_size(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        root_node = await _expanded_root(browser, pilot)
        kick_node = _node(root_node, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause(0.2)  # past PREVIEW_DEBOUNCE_SECONDS, see main_column.py
        text = _status_text(preview)
        assert "kick.wav" in text
        assert "0.50s" in text  # fixture is 4000 frames @ 8000Hz = 0.5s exactly
        # Computed from the actual file rather than hardcoded, so this
        # doesn't quietly drift if the wave module's own header size
        # (or human_bytes' own rounding) ever changes.
        assert human_bytes((samples_dir / "kick.wav").stat().st_size) in text


async def test_highlighting_a_file_shows_its_wav_format(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        root_node = await _expanded_root(browser, pilot)
        kick_node = _node(root_node, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause(0.2)  # past PREVIEW_DEBOUNCE_SECONDS, see main_column.py
        # fixture is 8000Hz, 16-bit, mono
        assert _format_text(preview) == "8kHz  16-bit  Mono"


async def test_waveform_plot_has_no_baked_in_background(samples_dir):
    # "auto" (the default) bakes $surface into a fixed RGB fill that
    # ignores the terminal's real background - "clear" emits no
    # background colour at all, so the widget's own transparent
    # background (and the terminal behind it) shows through instead.
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test():
        plot = app.query_one("#preview-waveform", PlotextPlot)
        assert plot.theme == "clear"


async def test_highlighting_a_folder_clears_the_pane(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        root_node = await _expanded_root(browser, pilot)
        drums_node = _node(root_node, "Drums")
        browser.focus()
        browser.move_cursor(drums_node)
        await pilot.pause()
        assert _status_text(preview) == ""
        assert _format_text(preview) == ""


async def test_rapidly_scrolling_past_a_file_never_loads_its_preview(samples_dir):
    """Landing on kick.wav only briefly, on the way to somewhere else,
    shouldn't trigger its (stat/duration/waveform) preview load at all -
    that's the whole point of debouncing it (see PREVIEW_DEBOUNCE_SECONDS
    in main_column.py): scrolling quickly through many files shouldn't
    generate one of these per file passed over."""
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        root_node = await _expanded_root(browser, pilot)
        kick_node = _node(root_node, "kick.wav")
        drums_node = _node(root_node, "Drums")
        browser.focus()

        browser.move_cursor(kick_node)
        await pilot.pause()  # well under PREVIEW_DEBOUNCE_SECONDS
        browser.move_cursor(drums_node)
        await pilot.pause(0.2)  # now past it - only Drums should ever have loaded

        assert _status_text(preview) == ""
        assert _format_text(preview) == ""


async def test_highlighting_a_tagged_file_shows_its_tags_on_the_date_line(samples_dir):
    db_path = samples_dir / "shmample.db"
    auto_assign_tag(samples_dir / "kick.wav", "kick", db_path)
    auto_assign_tag(samples_dir / "kick.wav", "808", db_path)

    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "kick.wav"))
        await pilot.pause(0.2)

        text = _status_text(preview)
        # Appended after date/duration/size rather than getting a row of
        # its own - the wav format line is untouched.
        assert "kick.wav" in text
        assert "Tags: " in text
        assert "808" in text
        assert "kick" in text
        assert _format_text(preview) == "8kHz  16-bit  Mono"


async def test_highlighting_an_untagged_file_adds_no_trailing_content(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "kick.wav"))
        await pilot.pause(0.2)

        assert "Tags:" not in _status_text(preview)
        assert _format_text(preview) == "8kHz  16-bit  Mono"


async def test_second_highlight_of_a_file_reads_from_the_cache(samples_dir, monkeypatch):
    """The whole point of caching preview info (01-auto-tagging.md) -
    decoding the waveform only happens once per file; every highlight
    after that reads sample_store instead."""
    calls = []
    original = preview_info_module.load_waveform_peaks

    def _counting_load_waveform_peaks(path, target_width):
        calls.append(path)
        return original(path, target_width)

    monkeypatch.setattr(preview_info_module, "load_waveform_peaks", _counting_load_waveform_peaks)

    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        root_node = await _expanded_root(browser, pilot)
        kick_node = _node(root_node, "kick.wav")
        drums_node = _node(root_node, "Drums")
        browser.focus()

        browser.move_cursor(kick_node)
        await pilot.pause(0.2)
        browser.move_cursor(drums_node)
        await pilot.pause()
        browser.move_cursor(kick_node)
        await pilot.pause(0.2)

        assert len(calls) == 1
        assert "0.50s" in _status_text(preview)


async def test_cached_preview_persists_across_widget_instances(samples_dir, tmp_path):
    """A fresh PreviewInfo pointed at the same db_path sees what an earlier
    one cached - proving the cache actually lives in the database, not
    just in-memory on the widget."""
    db_path = tmp_path / "shmample.db"
    kick_path = samples_dir / "kick.wav"

    first_app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    async with first_app.run_test() as pilot:
        browser = first_app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "kick.wav"))
        await pilot.pause(0.2)

    cached = sample_store.get_cached_preview(kick_path, db_path)
    assert cached is not None
    assert cached.duration_seconds == pytest.approx(0.5)


async def test_moving_between_file_and_folder_updates_pane(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        browser.focus()
        await pilot.pause()
        root_node = await _expanded_root(browser, pilot)

        kick_node = _node(root_node, "kick.wav")
        browser.move_cursor(kick_node)
        await pilot.pause(0.2)  # past PREVIEW_DEBOUNCE_SECONDS, see main_column.py
        assert "kick.wav" in _status_text(preview)

        drums_node = _node(root_node, "Drums")
        browser.move_cursor(drums_node)
        await pilot.pause()
        assert _status_text(preview) == ""
        assert _format_text(preview) == ""
