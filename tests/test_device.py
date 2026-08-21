import wave
from datetime import datetime
from types import SimpleNamespace

import pytest

from shmample import device
from shmample.config_store import Configuration
from shmample.device import (
    ALL_MODES,
    MODE_BACKUP,
    MODE_EXPORT,
    MODE_IMPORT,
    MODE_RESTORE,
    available_bytes_once_cleared,
    bank_folder,
    candidate_mount_roots,
    check_available_space,
    configuration_size_bytes,
    detect_device_state,
    human_bytes,
    pad_folder,
    pattern_filenames,
    send_configuration,
    truncation_risks,
)


def _configuration(assignments=None):
    now = datetime(2026, 1, 1)
    return Configuration(
        name="Kit", description="", created_at=now, modified_at=now, assignments=assignments or {}
    )


def _write_wav(path, seconds, frame_rate=44_100, channels=1, sample_width=2):
    """A real (if silent) WAV file of the given duration - only its
    header/frame count matters to truncation_risks, not its content."""
    frames = int(seconds * frame_rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00" * frames * channels * sample_width)


def test_bank_and_pad_folder_names():
    assert bank_folder("A") == "BANK_A"
    assert pad_folder(1) == "PAD_1"


def test_pattern_filenames_covers_all_64_slots():
    names = list(pattern_filenames())
    assert len(names) == 64
    assert names[0] == "P6_PTN1-01.PRM"
    assert names[-1] == "P6_PTN4-16.PRM"


def test_not_connected_when_mount_path_does_not_exist(tmp_path):
    state = detect_device_state(explicit_mount=tmp_path / "does-not-exist")
    assert state.connected is False
    assert state.mount is None
    assert state.mode is None


def test_connected_and_mode_detected_for_each_folder(tmp_path):
    for mode in ALL_MODES:
        mount = tmp_path / mode
        mount.mkdir()
        (mount / mode).mkdir()

        state = detect_device_state(explicit_mount=mount)

        assert state.connected is True
        assert state.mount == mount
        assert state.mode == mode


def test_connected_but_ambiguous_when_no_mode_folder_present(tmp_path):
    mount = tmp_path / "p6"
    mount.mkdir()
    (mount / "info.txt").write_text("something")

    state = detect_device_state(explicit_mount=mount)

    assert state.connected is True
    assert state.mode is None


def test_connected_but_ambiguous_when_multiple_mode_folders_present(tmp_path):
    # Shouldn't happen given the device only exposes one mode per
    # power-cycle, but don't guess which one is "real" if it does.
    mount = tmp_path / "p6"
    mount.mkdir()
    (mount / MODE_IMPORT).mkdir()
    (mount / MODE_EXPORT).mkdir()

    state = detect_device_state(explicit_mount=mount)

    assert state.connected is True
    assert state.mode is None


def test_import_sample_layout_is_detected(tmp_path):
    mount = tmp_path / "p6"
    (mount / MODE_IMPORT / bank_folder("A") / pad_folder(1)).mkdir(parents=True)

    state = detect_device_state(explicit_mount=mount)

    assert state.mode == MODE_IMPORT


def test_candidate_mount_roots_includes_platform_specific_paths(monkeypatch):
    import platform as platform_module

    monkeypatch.setattr(platform_module, "system", lambda: "Darwin")
    darwin_candidates = candidate_mount_roots()
    assert any(str(p) == "/Volumes/P-6" for p in darwin_candidates)

    monkeypatch.setattr(platform_module, "system", lambda: "Linux")
    linux_candidates = candidate_mount_roots()
    assert any(str(p) == "/run/media/P-6" for p in linux_candidates)
    assert any(str(p) == "/media/P-6" for p in linux_candidates)
    assert any(str(p) == "/mnt/P-6" for p in linux_candidates)


def test_candidate_mount_roots_has_no_duplicates(monkeypatch):
    import platform as platform_module

    monkeypatch.setattr(platform_module, "system", lambda: "Linux")
    candidates = candidate_mount_roots()
    assert len(candidates) == len(set(candidates))


def test_send_configuration_copies_each_assignment_to_its_pad_folder(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    mount = tmp_path / "mount"

    result = send_configuration(_configuration({("A", "1"): str(sample)}), mount)

    assert result.sent == 1
    assert result.missing == []
    copied = mount / MODE_IMPORT / bank_folder("A") / pad_folder(1) / "kick.wav"
    assert copied.read_bytes() == b"kick"


def test_send_configuration_skips_missing_sources_and_reports_them(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    missing = str(tmp_path / "gone.wav")
    mount = tmp_path / "mount"

    result = send_configuration(
        _configuration({("A", "1"): str(sample), ("A", "2"): missing}), mount
    )

    assert result.sent == 1
    assert result.missing == [missing]
    assert not (mount / MODE_IMPORT / bank_folder("A") / pad_folder(2)).exists()


def test_send_configuration_clears_stale_files_before_copying_the_replacement(tmp_path):
    new_sample = tmp_path / "snare.wav"
    new_sample.write_bytes(b"snare")
    mount = tmp_path / "mount"
    pad_dir = mount / MODE_IMPORT / bank_folder("A") / pad_folder(1)
    pad_dir.mkdir(parents=True)
    (pad_dir / "old.wav").write_bytes(b"old")

    result = send_configuration(_configuration({("A", "1"): str(new_sample)}), mount)

    assert result.sent == 1
    assert sorted(p.name for p in pad_dir.iterdir()) == ["snare.wav"]


def test_send_configuration_never_deletes_or_recreates_existing_pad_folders(tmp_path):
    # The user's specific hypothesis for why real imports weren't
    # working: recreating BANK_x/PAD_y folders on the device's actual
    # FAT-formatted volume might lose attributes/permissions a plain
    # host-side mkdir doesn't replicate. Checked via inode identity, not
    # just "a file ends up in there somehow" - a delete-then-recreate
    # would still pass a weaker check.
    new_sample = tmp_path / "snare.wav"
    new_sample.write_bytes(b"snare")
    mount = tmp_path / "mount"
    pad_dir = mount / MODE_IMPORT / bank_folder("A") / pad_folder(1)
    pad_dir.mkdir(parents=True)
    original_inode = pad_dir.stat().st_ino

    send_configuration(_configuration({("A", "1"): str(new_sample)}), mount)

    assert pad_dir.stat().st_ino == original_inode


def test_send_configuration_produces_no_file_for_a_pad_whose_source_is_missing(tmp_path):
    mount = tmp_path / "mount"
    pad_dir = mount / MODE_IMPORT / bank_folder("A") / pad_folder(1)
    pad_dir.mkdir(parents=True)
    (pad_dir / "old.wav").write_bytes(b"old")

    result = send_configuration(
        _configuration({("A", "1"): str(tmp_path / "gone.wav")}), mount
    )

    # Every existing file under IMPORT is cleared up front regardless of
    # any individual source being missing - "old.wav" was never "the
    # current sample on that pad" (IMPORT doesn't reflect device state),
    # so there's nothing worth protecting it from being cleared too. The
    # *folder* itself is left alone either way - only files are removed,
    # never directories (see send_configuration's docstring for why).
    assert result.sent == 0
    assert pad_dir.is_dir()
    assert list(pad_dir.iterdir()) == []


def test_send_configuration_clears_files_in_untouched_pads_too(tmp_path):
    # The actual bug report this fixes: previous sends only ever cleared
    # the specific pads they wrote, so unrelated leftovers (in practice,
    # the device's own factory demo kit) filled up the whole tiny IMPORT
    # partition over time, leaving no room for a new send at all.
    new_sample = tmp_path / "snare.wav"
    new_sample.write_bytes(b"snare")
    mount = tmp_path / "mount"
    untouched_pad_dir = mount / MODE_IMPORT / bank_folder("B") / pad_folder(3)
    untouched_pad_dir.mkdir(parents=True)
    (untouched_pad_dir / "factory-demo.wav").write_bytes(b"demo")

    result = send_configuration(_configuration({("A", "1"): str(new_sample)}), mount)

    assert result.sent == 1
    # The folder survives (never deleted, per the user's report that
    # recreating device folders may be what broke the import in the
    # first place) - but its stale content is still gone, which is the
    # actual space-freeing behaviour this test exists to check.
    assert untouched_pad_dir.is_dir()
    assert list(untouched_pad_dir.iterdir()) == []


def test_send_configuration_with_no_assignments_does_nothing(tmp_path):
    result = send_configuration(_configuration(), tmp_path / "mount")

    assert result.sent == 0
    assert result.missing == []


def test_human_bytes_formats_common_sizes():
    assert human_bytes(500) == "500B"
    assert human_bytes(1536) == "1.5KB"
    assert human_bytes(5 * 1024 * 1024) == "5.0MB"


def test_check_available_space_fits_when_theres_room(tmp_path, monkeypatch):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 1000)
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=10_000)
    )

    result = check_available_space(_configuration({("A", "1"): str(sample)}), tmp_path / "mount")

    assert result.fits is True
    assert result.needed_bytes == 1000
    assert result.free_bytes == 10_000


def test_check_available_space_does_not_fit_when_free_space_is_too_small(tmp_path, monkeypatch):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 1000)
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=500)
    )

    result = check_available_space(_configuration({("A", "1"): str(sample)}), tmp_path / "mount")

    assert result.fits is False
    assert result.needed_bytes == 1000
    assert result.free_bytes == 500


def test_check_available_space_credits_back_the_entire_existing_import_tree(tmp_path, monkeypatch):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 1000)
    mount = tmp_path / "mount"
    # One stale file in a pad this send touches, one in a pad it
    # doesn't - send_configuration wipes the whole IMPORT tree
    # regardless, so both should be credited back, not just the former.
    touched_pad_dir = mount / MODE_IMPORT / bank_folder("A") / pad_folder(1)
    touched_pad_dir.mkdir(parents=True)
    (touched_pad_dir / "old.wav").write_bytes(b"y" * 600)
    untouched_pad_dir = mount / MODE_IMPORT / bank_folder("B") / pad_folder(3)
    untouched_pad_dir.mkdir(parents=True)
    (untouched_pad_dir / "factory-demo.wav").write_bytes(b"z" * 300)
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=200)
    )

    result = check_available_space(_configuration({("A", "1"): str(sample)}), mount)

    # needed_bytes is the plain 1000 - not netted against the existing
    # tree any more (see SpaceCheck's docstring for why: mixing a netted
    # "needed" with a raw "free" made an easily-fixed case look
    # indistinguishable from a genuine device-too-small one). Instead,
    # free_bytes absorbs the credit: 200 raw free + 900 (600 + 300)
    # reclaimable by wiping the whole tree first = 1100, which fits 1000.
    assert result.needed_bytes == 1000
    assert result.free_bytes == 1100
    assert result.fits is True


def test_check_available_space_does_not_fit_even_after_crediting_the_whole_tree(
    tmp_path, monkeypatch
):
    # The genuinely-too-big-for-the-device case: even once every byte the
    # existing tree would give back is counted, the configuration still
    # doesn't fit - no amount of clearing stale content changes that.
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 1000)
    mount = tmp_path / "mount"
    pad_dir = mount / MODE_IMPORT / bank_folder("A") / pad_folder(1)
    pad_dir.mkdir(parents=True)
    (pad_dir / "old.wav").write_bytes(b"y" * 100)
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=50)
    )

    result = check_available_space(_configuration({("A", "1"): str(sample)}), mount)

    # 1000 needed; only 150 available even once cleared (50 raw free +
    # 100 reclaimable).
    assert result.needed_bytes == 1000
    assert result.free_bytes == 150
    assert result.fits is False


def test_check_available_space_ignores_missing_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=0)
    )

    result = check_available_space(
        _configuration({("A", "1"): str(tmp_path / "gone.wav")}), tmp_path / "mount"
    )

    assert result.needed_bytes == 0
    assert result.fits is True


def test_configuration_size_bytes_sums_existing_sources_only(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 1000)

    config = _configuration(
        {("A", "1"): str(sample), ("A", "2"): str(tmp_path / "gone.wav")}
    )

    assert configuration_size_bytes(config) == 1000


def test_configuration_size_bytes_is_zero_for_no_assignments():
    assert configuration_size_bytes(_configuration()) == 0


def test_available_bytes_once_cleared_adds_free_space_and_reclaimable_tree(
    tmp_path, monkeypatch
):
    mount = tmp_path / "mount"
    pad_dir = mount / MODE_IMPORT / bank_folder("A") / pad_folder(1)
    pad_dir.mkdir(parents=True)
    (pad_dir / "old.wav").write_bytes(b"x" * 400)
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=100)
    )

    assert available_bytes_once_cleared(mount) == 500


def test_available_bytes_once_cleared_with_no_existing_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=100)
    )

    assert available_bytes_once_cleared(tmp_path / "mount") == 100


def test_truncation_risks_flags_a_sample_longer_than_its_pad_fits(tmp_path):
    # Budget is a fixed ~520KB/pad (derived from the manual's 5.9s @
    # 44.1kHz mono figure) - at 96kHz mono that's only ~2.7s, so a 5s
    # file at that rate is a small, fast-to-write way to trigger it.
    long_sample = tmp_path / "long.wav"
    _write_wav(long_sample, seconds=5, frame_rate=96_000, channels=1)

    risks = truncation_risks(_configuration({("A", "1"): str(long_sample)}))

    assert len(risks) == 1
    risk = risks[0]
    assert (risk.bank, risk.pad) == ("A", "1")
    assert risk.sample_path == str(long_sample)
    assert risk.actual_seconds == pytest.approx(5.0, abs=0.01)
    assert risk.max_seconds < risk.actual_seconds


def test_truncation_risks_says_nothing_about_a_sample_that_fits(tmp_path):
    short_sample = tmp_path / "short.wav"
    _write_wav(short_sample, seconds=1, frame_rate=96_000, channels=1)

    assert truncation_risks(_configuration({("A", "1"): str(short_sample)})) == []


def test_truncation_risks_skips_a_missing_source(tmp_path):
    config = _configuration({("A", "1"): str(tmp_path / "gone.wav")})
    assert truncation_risks(config) == []
