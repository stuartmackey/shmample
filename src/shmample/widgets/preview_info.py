from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
from textual_plotext import PlotextPlot

from shmample.device import human_bytes
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

    can_focus=True purely so numbered pane-jump (3, see app.py) has
    somewhere to land - this pane has no bindings/interaction of its own.
    """

    can_focus = True

    DEFAULT_CSS = """
    PreviewInfo {
        height: 1fr;
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
            duration = get_duration_seconds(path)
            duration_text = _format_duration(duration) if duration is not None else "?"
            date_label.update(
                f"{path.name}  {created:%Y-%m-%d %H:%M}  {duration_text}  {human_bytes(stat.st_size)}"
            )

            wav_format = get_format_info(path)
            format_label.update(_format_wav_format(wav_format) if wav_format is not None else "")

            width = plot.size.width or 40
            peaks = load_waveform_peaks(path, target_width=width)
            if peaks:
                plt.plot(peaks, marker="braille")
                plt.plot([-p for p in peaks], marker="braille")

        plt.frame(False)
        plt.xticks([])
        plt.yticks([])
        plt.ylim(-1, 1)
        plot.refresh()
