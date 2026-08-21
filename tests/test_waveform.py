import struct
import wave

from shmample.waveform import get_duration_seconds, get_format_info, load_waveform_peaks


def _write_constant_tone(path, sample_width_bytes, amplitude=0.5, seconds=0.5, sample_rate=8000):
    """A wav whose samples alternate +peak/-peak at the given amplitude,
    written directly at the byte level so every real WAV bit depth (8-bit
    unsigned, 16/24/32-bit signed) is covered, not just what a single
    `struct` format code can pack."""
    n_samples = int(sample_rate * seconds)
    full_scale = 128 if sample_width_bytes == 1 else (1 << (sample_width_bytes * 8 - 1))
    peak = int(full_scale * amplitude)

    frames = bytearray()
    for i in range(n_samples):
        value = peak if i % 2 == 0 else -peak
        if sample_width_bytes == 1:
            frames += ((value + 128) & 0xFF).to_bytes(1, "little")
        else:
            frames += value.to_bytes(sample_width_bytes, "little", signed=True)

    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(sample_width_bytes)
        f.setframerate(sample_rate)
        f.writeframes(bytes(frames))


def test_decodes_16bit_wav_into_normalised_peaks(tmp_path):
    wav_path = tmp_path / "tone16.wav"
    _write_constant_tone(wav_path, sample_width_bytes=2, amplitude=0.5)

    peaks = load_waveform_peaks(wav_path, target_width=40)

    assert len(peaks) == 40
    assert all(0.4 < p < 0.6 for p in peaks)


def test_decodes_8bit_wav_into_normalised_peaks(tmp_path):
    wav_path = tmp_path / "tone8.wav"
    _write_constant_tone(wav_path, sample_width_bytes=1, amplitude=0.5)

    peaks = load_waveform_peaks(wav_path, target_width=40)

    assert len(peaks) == 40
    assert all(0.4 < p < 0.6 for p in peaks)


def test_decodes_24bit_wav_into_normalised_peaks(tmp_path):
    # 24-bit was the actual bug this test suite exists to catch: Python's
    # `array` module has no native typecode for 3-byte samples, so this
    # width needs its own decode path rather than array.frombytes().
    wav_path = tmp_path / "tone24.wav"
    _write_constant_tone(wav_path, sample_width_bytes=3, amplitude=0.5)

    peaks = load_waveform_peaks(wav_path, target_width=40)

    assert len(peaks) == 40
    assert all(0.4 < p < 0.6 for p in peaks)


def test_decodes_32bit_int_wav_into_normalised_peaks(tmp_path):
    wav_path = tmp_path / "tone32.wav"
    _write_constant_tone(wav_path, sample_width_bytes=4, amplitude=0.5)

    peaks = load_waveform_peaks(wav_path, target_width=40)

    assert len(peaks) == 40
    assert all(0.4 < p < 0.6 for p in peaks)


def test_stereo_wav_uses_first_channel_only(tmp_path):
    wav_path = tmp_path / "stereo.wav"
    n_samples = 4000
    frames = bytearray()
    for i in range(n_samples):
        left = 16000 if i % 2 == 0 else -16000
        right = 100  # very different amplitude - would corrupt the result if not skipped
        frames += struct.pack("<hh", left, right)
    with wave.open(str(wav_path), "w") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(bytes(frames))

    peaks = load_waveform_peaks(wav_path, target_width=40)

    assert len(peaks) == 40
    assert all(p > 0.4 for p in peaks)  # reflects the left channel's amplitude, not the right's


def test_empty_file_returns_no_peaks(tmp_path):
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")

    assert load_waveform_peaks(empty, target_width=40) == []


def test_missing_file_returns_no_peaks(tmp_path):
    assert load_waveform_peaks(tmp_path / "does-not-exist.wav", target_width=40) == []


def test_duration_matches_frame_count_over_frame_rate(tmp_path):
    wav_path = tmp_path / "half_second.wav"
    _write_constant_tone(wav_path, sample_width_bytes=2, seconds=0.5, sample_rate=8000)

    assert get_duration_seconds(wav_path) == 0.5


def test_duration_of_empty_file_is_none(tmp_path):
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")

    assert get_duration_seconds(empty) is None


def test_duration_of_missing_file_is_none(tmp_path):
    assert get_duration_seconds(tmp_path / "does-not-exist.wav") is None


def test_format_info_reports_rate_width_and_channels(tmp_path):
    wav_path = tmp_path / "tone24_stereo.wav"
    with wave.open(str(wav_path), "w") as f:
        f.setnchannels(2)
        f.setsampwidth(3)
        f.setframerate(48000)
        f.writeframes(b"\x00\x00\x00" * 2 * 10)  # 10 frames, 2 channels, 3 bytes each

    fmt = get_format_info(wav_path)

    assert fmt.frame_rate == 48000
    assert fmt.sample_width_bytes == 3
    assert fmt.channels == 2


def test_format_info_of_missing_file_is_none(tmp_path):
    assert get_format_info(tmp_path / "does-not-exist.wav") is None
