"""Converts an arbitrary source sample to a device's required on-disk audio
shape (sample rate, channel count, PCM subtype) before it's written to a
pack/bank - shared by any device exporter that needs samples to land in a
specific format rather than whatever the source file happens to be in.

Existed because of a real, live-hardware-confirmed Circuit Tracks bug (see
docs/tasks/04-export-to-ct.md's round 6): a pack whose samples aren't
exactly 48kHz is never recognised by the device at all, even though the
files are otherwise perfectly valid WAVs - and separately, any extra RIFF
chunk beyond a bare `fmt `/`data` pair (present on every sample from every
commercial sample library tested, absent on every genuine Novation-authored
one) is also enough to break recognition. `sf.write` below always re-writes
through libsndfile rather than special-casing "source already matches", to
guarantee that bare-chunk shape regardless of what the source file happened
to be carrying.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr


@dataclass(frozen=True)
class SampleFormat:
    frame_rate: int
    channels: int
    subtype: str = "PCM_16"


def convert_sample(source: Path, dest: Path, target: SampleFormat) -> None:
    data, rate = sf.read(source, dtype="float32", always_2d=True)

    data = _remix_channels(data, target.channels)
    if rate != target.frame_rate:
        data = soxr.resample(data, rate, target.frame_rate)

    sf.write(dest, data, target.frame_rate, subtype=target.subtype, format="WAV")


def _remix_channels(data: np.ndarray, channels: int) -> np.ndarray:
    if data.shape[1] == channels:
        return data
    if channels == 1:
        return data.mean(axis=1, keepdims=True)
    if data.shape[1] == 1:
        return np.repeat(data, channels, axis=1)
    return data[:, :channels]
