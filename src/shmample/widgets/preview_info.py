from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual_plotext import PlotextPlot

from shmample import sample_store, tag_store
from shmample.device import human_bytes
from shmample.sample_store import CachedPreview
from shmample.waveform import WavFormat, get_duration_seconds, get_format_info, load_waveform_peaks


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}:{remainder:05.2f}"


def _format_channels(channels: int) -> str:
    return {1: "Mono", 2: "Stereo"}.get(channels, f"{channels}ch")


def _format_sample_rate(frame_rate: int) -> str:
    return f"{frame_rate / 1000:g}kHz"


def _format_wav_format(fmt: WavFormat) -> str:
    return (
        f"{_format_sample_rate(fmt.frame_rate)}  "
        f"{fmt.sample_width_bytes * 8}-bit  "
        f"{_format_channels(fmt.channels)}"
    )


class PreviewInfo(Vertical):
    """Small pane below the file browser: creation date/duration, wav
    format, and a static waveform for whatever's highlighted. Blank for
    folders/nothing.

    The waveform plot deliberately has no frame/axes/ticks - at the
    handful of rows this pane gets, that chrome ate most of the space
    and left too little vertical resolution to see any shape.

    can_focus=True purely so numbered pane-jump (6, see app.py) has
    somewhere to land - this pane has no bindings/interaction of its own.

    Duration/format/waveform are cached in sample_store (01-auto-tagging.md)
    keyed on the highlighted file's path - a first hit computes and persists
    them, every later highlight of the same file just reads the cache
    instead of re-decoding it. Tags come from tag_store instead - not
    cached here, since they can change (auto-tag, or later manual editing)
    independently of the file itself. They're appended to the date/
    duration/size line rather than getting a row of their own - this pane
    is only a handful of rows tall to begin with.
    """

    can_focus = True

    # Borders itself (as TagBrowser/HoldingArea/AssignmentGrid do) rather
    # than relying on a parent's CSS - it sits in #browse-column (app.py's
    # compose), not nested inside a column that borders its children for
    # it the way MainColumn still does for ConfigList/FileBrowser.
    DEFAULT_CSS = """
    PreviewInfo {
        height: 1fr;
        border: round $foreground;
    }
    PreviewInfo:focus {
        border: round $primary;
    }
    PreviewInfo > #preview-date {
        height: 1;
    }
    PreviewInfo > #preview-format {
        height: 1;
    }
    PreviewInfo > #preview-waveform {
        height: 1fr;
    }
    """

    def __init__(self, db_path: Path | None = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Resolved at call time, not a mutable default parameter - same
        # reasoning as FileBrowser's own settings_path, so tests can
        # redirect persistence to a tmp_path.
        self.db_path = db_path if db_path is not None else sample_store.DEFAULT_DB_PATH

    def compose(self) -> ComposeResult:
        yield Static("", id="preview-date")
        yield Static("", id="preview-format")
        plot = PlotextPlot(id="preview-waveform")
        # Default "auto" theme bakes $surface/$foreground into a fixed
        # RGB fill - under the ansi themes that resolves to a literal
        # colour (looks like plain black) rather than the terminal's
        # actual background, unlike every other widget here (which get
        # that for free via Widget's own `background: transparent`).
        # "clear" emits no background colour codes at all, so the
        # widget's real transparent background shows through instead.
        plot.theme = "clear"
        yield plot

    def show(self, path: Path | None) -> None:
        date_label = self.query_one("#preview-date", Static)
        format_label = self.query_one("#preview-format", Static)
        plot = self.query_one("#preview-waveform", PlotextPlot)
        plt = plot.plt
        plt.clear_data()

        if path is None:
            date_label.update("")
            format_label.update("")
        else:
            stat = path.stat()
            created = datetime.fromtimestamp(stat.st_ctime)

            cached = sample_store.get_cached_preview(path, self.db_path)
            if cached is None:
                cached = CachedPreview(
                    duration_seconds=get_duration_seconds(path),
                    wav_format=get_format_info(path),
                    # Cached at a fixed, display-independent resolution
                    # (sample_store.resample_envelope handles fitting it
                    # to whatever width the plot has at render time) -
                    # not the plot's own current width, which would tie
                    # the cached data to whatever size the pane happened
                    # to be the first time this file was ever previewed.
                    envelope=load_waveform_peaks(
                        path, target_width=sample_store.ENVELOPE_RESOLUTION
                    ),
                )
                sample_store.store_preview(path, cached, self.db_path)

            duration_text = (
                _format_duration(cached.duration_seconds)
                if cached.duration_seconds is not None
                else "?"
            )
            date_line = (
                f"{path.name}  {created:%Y-%m-%d %H:%M}  {duration_text}  "
                f"{human_bytes(stat.st_size)}"
            )
            tags = sorted(tag_store.tags_for_sample(path, self.db_path))
            if tags:
                date_line += f"  Tags: {', '.join(tags)}"
            date_label.update(date_line)

            format_label.update(
                _format_wav_format(cached.wav_format) if cached.wav_format is not None else ""
            )

            width = plot.size.width or 40
            peaks = sample_store.resample_envelope(cached.envelope, width)
            if peaks:
                plt.plot(peaks, marker="braille")
                plt.plot([-p for p in peaks], marker="braille")

        plt.frame(False)
        plt.xticks([])
        plt.yticks([])
        plt.ylim(-1, 1)
        plot.refresh()
