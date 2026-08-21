import array
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WavFormat:
    frame_rate: int
    sample_width_bytes: int
    channels: int


def get_format_info(path: Path) -> WavFormat | None:
    """Sample rate/bit depth/channel count, straight from the wav header -
    same "no sample decoding needed" reasoning as get_duration_seconds.

    Returns None if the file can't be read.
    """
    try:
        with wave.open(str(path), "rb") as wav_file:
            return WavFormat(
                frame_rate=wav_file.getframerate(),
                sample_width_bytes=wav_file.getsampwidth(),
                channels=wav_file.getnchannels(),
            )
    except Exception:
        return None

# array typecodes for the sample widths it can unpack natively. 24-bit has
# no native typecode (WAV's 3-byte-per-sample PCM isn't a C integer size),
# so it's handled separately below.
_ARRAY_TYPECODE = {1: "B", 2: "h", 4: "i"}


def _decode_samples(raw: bytes, sample_width: int, n_channels: int) -> list[float]:
    """Decode raw PCM bytes to floats in [-1, 1], first channel only."""
    if sample_width == 3:
        frame_size = sample_width * n_channels
        full_scale = 1 << 23
        return [
            (
                int.from_bytes(raw[i:i + 3], "little", signed=True)
            )
            / full_scale
            for i in range(0, len(raw) - frame_size + 1, frame_size)
        ]

    typecode = _ARRAY_TYPECODE[sample_width]
    samples = array.array(typecode)
    samples.frombytes(raw[: len(raw) - (len(raw) % (sample_width * n_channels))])
    if n_channels > 1:
        samples = samples[::n_channels]

    if sample_width == 1:
        # 8-bit PCM is the odd one out in the WAV spec: unsigned, centred on 128.
        return [(s - 128) / 128 for s in samples]
    full_scale = 1 << (sample_width * 8 - 1)
    return [s / full_scale for s in samples]


def get_duration_seconds(path: Path) -> float | None:
    """A wav's duration in seconds, from its header only (frame count /
    frame rate) - no need to decode any sample data for this.

    Returns None if the file can't be read - same "degrade gracefully"
    reasoning as load_waveform_peaks below.
    """
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return None
            return wav_file.getnframes() / frame_rate
    except Exception:
        return None


def load_waveform_peaks(path: Path, target_width: int) -> list[float]:
    """Downsample a wav file to one peak amplitude (0-1) per column.

    Handles 8/16/24/32-bit integer PCM - the common bit depths for sample
    libraries (24-bit especially, which is very common and was originally
    missed here since Python's `array` module has no native type for it).
    32-bit float PCM (as opposed to 32-bit int) isn't distinguished by
    stdlib `wave` and isn't handled - it would decode as int and look wrong,
    though not crash.

    Returns an empty list if the file can't be decoded (missing, corrupt,
    empty, or an unsupported sample width) - callers show "no waveform"
    rather than crash for a bad file.
    """
    try:
        with wave.open(str(path), "rb") as wav_file:
            sample_width = wav_file.getsampwidth()
            n_channels = wav_file.getnchannels()
            raw = wav_file.readframes(wav_file.getnframes())
    except Exception:
        # Deliberately broad: a truncated/corrupt/empty file can raise all
        # sorts of things from within wave.py (EOFError, struct.error, its
        # own wave.Error, ...) - any of them just means "no waveform to
        # show", not "crash the app".
        return []

    if sample_width not in (1, 2, 3, 4) or n_channels < 1:
        return []

    samples = _decode_samples(raw, sample_width, n_channels)

    total = len(samples)
    if total == 0 or target_width <= 0:
        return []

    bucket_size = max(1, total // target_width)
    peaks = []
    for start in range(0, total, bucket_size):
        chunk = samples[start:start + bucket_size]
        if not chunk:
            continue
        peaks.append(max(abs(min(chunk)), abs(max(chunk))))
    return peaks
