from shmample.sample_store import (
    CachedPreview,
    get_cached_preview,
    resample_envelope,
    store_preview,
)
from shmample.waveform import WavFormat


def test_missing_entry_returns_none(tmp_path):
    db_path = tmp_path / "shmample.db"
    assert get_cached_preview(tmp_path / "kick.wav", db_path) is None


def test_store_and_get_round_trips_all_fields(tmp_path):
    db_path = tmp_path / "shmample.db"
    path = tmp_path / "kick.wav"
    preview = CachedPreview(
        duration_seconds=0.5,
        wav_format=WavFormat(frame_rate=8000, sample_width_bytes=2, channels=1),
        envelope=[0.1, 0.5, 1.0, 0.2],
    )

    store_preview(path, preview, db_path)
    loaded = get_cached_preview(path, db_path)

    assert loaded == preview


def test_store_round_trips_a_failed_probe(tmp_path):
    """A file that couldn't be decoded at all still gets cached (None
    duration/format, empty envelope) - see sample_store.store_preview's
    own docstring for why this matters."""
    db_path = tmp_path / "shmample.db"
    path = tmp_path / "corrupt.wav"
    preview = CachedPreview(duration_seconds=None, wav_format=None, envelope=[])

    store_preview(path, preview, db_path)
    loaded = get_cached_preview(path, db_path)

    assert loaded == preview


def test_storing_again_overwrites_the_previous_entry(tmp_path):
    db_path = tmp_path / "shmample.db"
    path = tmp_path / "kick.wav"
    store_preview(
        path,
        CachedPreview(duration_seconds=0.5, wav_format=None, envelope=[0.1]),
        db_path,
    )

    updated = CachedPreview(duration_seconds=1.0, wav_format=None, envelope=[0.9])
    store_preview(path, updated, db_path)

    assert get_cached_preview(path, db_path) == updated


def test_different_paths_are_cached_independently(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = CachedPreview(duration_seconds=0.5, wav_format=None, envelope=[0.1])
    snare = CachedPreview(duration_seconds=0.3, wav_format=None, envelope=[0.9])

    store_preview(tmp_path / "kick.wav", kick, db_path)
    store_preview(tmp_path / "snare.wav", snare, db_path)

    assert get_cached_preview(tmp_path / "kick.wav", db_path) == kick
    assert get_cached_preview(tmp_path / "snare.wav", db_path) == snare


def test_resample_envelope_is_a_no_op_when_already_narrower_than_width():
    assert resample_envelope([0.1, 0.2, 0.3], width=10) == [0.1, 0.2, 0.3]


def test_resample_envelope_downsamples_to_the_requested_width():
    envelope = [0.1, 0.9, 0.2, 0.8, 0.3, 0.7, 0.4, 0.6]
    resampled = resample_envelope(envelope, width=4)
    assert len(resampled) == 4
    # Bucket-max, same as waveform.load_waveform_peaks - each bucket keeps
    # its own loudest point rather than averaging detail away.
    assert resampled == [0.9, 0.8, 0.7, 0.6]


def test_resample_envelope_handles_empty_input():
    assert resample_envelope([], width=10) == []


def test_resample_envelope_handles_zero_width():
    assert resample_envelope([0.1, 0.2], width=0) == []
