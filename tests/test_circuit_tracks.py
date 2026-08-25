import pytest

from shmample import device
from shmample.circuit_tracks import (
    MAX_PACK_INDEX,
    MIN_PACK_INDEX,
    find_ct_cards,
    is_writable,
    list_pack_slots,
    send_pack_to_slot,
)
from shmample.config_store import Configuration, Pack


def _configuration(holding=()):
    from datetime import datetime

    return Configuration(
        pack=Pack(
            name="My Kit",
            description="",
            created_at=datetime(2026, 1, 1),
            modified_at=datetime(2026, 1, 1),
            holding=list(holding),
        )
    )


def test_is_writable_true_for_a_normal_directory(tmp_path):
    assert is_writable(tmp_path) is True


def test_is_writable_false_for_a_read_only_directory(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    mount.chmod(0o555)
    try:
        assert is_writable(mount) is False
    finally:
        mount.chmod(0o755)  # restore so tmp_path's own cleanup can remove it


def test_find_ct_cards_only_returns_mounts_with_a_tracks_folder(tmp_path, monkeypatch):
    ct_card = tmp_path / "ct-card"
    (ct_card / "Tracks").mkdir(parents=True)
    other_drive = tmp_path / "other-drive"
    other_drive.mkdir()
    missing = tmp_path / "unplugged"  # in the candidate list but doesn't actually exist

    monkeypatch.setattr(device, "candidate_mount_roots", lambda: [ct_card, other_drive, missing])

    assert find_ct_cards() == [ct_card]


def test_list_pack_slots_all_empty_on_a_freshly_formatted_card(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()

    slots = list_pack_slots(mount)

    assert [slot.index for slot in slots] == list(range(MIN_PACK_INDEX, MAX_PACK_INDEX + 1))
    assert all(not slot.occupied for slot in slots)


def test_list_pack_slots_flags_existing_packs_by_folder_number(tmp_path):
    mount = tmp_path / "mount"
    (mount / "Tracks" / "00_Synthwave").mkdir(parents=True)
    (mount / "Tracks" / "05_Peak Sample Pack").mkdir(parents=True)

    slots = {slot.index: slot for slot in list_pack_slots(mount)}

    assert slots[2].occupied and slots[2].name == "Synthwave"
    assert slots[7].occupied and slots[7].name == "Peak Sample Pack"
    assert not slots[3].occupied


def test_list_pack_slots_skips_an_entry_that_cant_be_stat_d(tmp_path, monkeypatch):
    # Reproduces a real crash seen against actual hardware: reading one
    # folder's metadata off the SD card hit an intermittent I/O error
    # while every other entry on the same card read fine.
    from pathlib import Path

    mount = tmp_path / "mount"
    (mount / "Tracks" / "00_Synthwave").mkdir(parents=True)
    flaky = mount / "Tracks" / "05_Peak Sample Pack"
    flaky.mkdir()

    real_is_dir = Path.is_dir

    def flaky_is_dir(self):
        if self == flaky:
            raise OSError(5, "Input/output error")
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", flaky_is_dir)

    slots = {slot.index: slot for slot in list_pack_slots(mount)}

    assert slots[2].occupied and slots[2].name == "Synthwave"
    assert not slots[7].occupied  # the flaky entry is skipped, not crashed on


def test_send_pack_to_slot_writes_holding_order_into_a_new_slot(tmp_path):
    kick = tmp_path / "kick.wav"
    kick.write_bytes(b"kick-data")
    snare = tmp_path / "snare.wav"
    snare.write_bytes(b"snare-data")
    mount = tmp_path / "mount"

    result = send_pack_to_slot(_configuration([str(kick), str(snare)]), mount, pack_index=2)

    assert result.exported == 2
    assert result.missing == []
    pack_dir = mount / "Tracks" / "00_My Kit"
    assert result.destination == pack_dir
    assert (pack_dir / "meta" / "00_META.ncm").read_bytes() == b"\x00\x00"
    assert (pack_dir / "PCM" / "00_kick.wav").read_bytes() == b"kick-data"
    assert (pack_dir / "PCM" / "01_snare.wav").read_bytes() == b"snare-data"


def test_send_pack_to_slot_skips_missing_sources_and_reports_them(tmp_path):
    kick = tmp_path / "kick.wav"
    kick.write_bytes(b"kick-data")
    missing = str(tmp_path / "gone.wav")
    mount = tmp_path / "mount"

    result = send_pack_to_slot(_configuration([str(kick), missing]), mount, pack_index=2)

    assert result.exported == 1
    assert result.missing == [missing]
    pack_dir = mount / "Tracks" / "00_My Kit"
    assert list((pack_dir / "PCM").iterdir()) == [pack_dir / "PCM" / "00_kick.wav"]


def test_send_pack_to_slot_replaces_whatever_already_occupied_that_slot(tmp_path):
    mount = tmp_path / "mount"
    old_pack = mount / "Tracks" / "00_Old Pack"
    (old_pack / "PCM").mkdir(parents=True)
    (old_pack / "PCM" / "00_old.wav").write_bytes(b"old-data")

    kick = tmp_path / "kick.wav"
    kick.write_bytes(b"kick-data")

    result = send_pack_to_slot(_configuration([str(kick)]), mount, pack_index=2)

    assert not old_pack.exists()
    assert result.destination == mount / "Tracks" / "00_My Kit"
    assert (result.destination / "PCM" / "00_kick.wav").read_bytes() == b"kick-data"


def test_send_pack_to_slot_rejects_an_out_of_range_index(tmp_path):
    mount = tmp_path / "mount"

    with pytest.raises(ValueError):
        send_pack_to_slot(_configuration(), mount, pack_index=1)

    with pytest.raises(ValueError):
        send_pack_to_slot(_configuration(), mount, pack_index=33)
