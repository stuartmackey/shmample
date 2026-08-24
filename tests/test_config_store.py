import json
from datetime import datetime

from shmample.config_store import (
    Configuration,
    Pack,
    delete_configuration,
    export_holding,
    list_configurations,
    save_configuration,
)


def test_save_and_list_round_trips_all_fields(tmp_path):
    created = datetime(2026, 1, 1, 12, 0, 0)
    modified = datetime(2026, 1, 2, 9, 30, 0)
    config = Configuration(
        pack=Pack(
            name="Drum Kit",
            description="A test kit",
            created_at=created,
            modified_at=modified,
            holding=["/samples/tom.wav", "/samples/clap.wav"],
        ),
        assignments={("A", "1"): "/samples/kick.wav", ("B", "3"): "/samples/snare.wav"},
    )

    save_configuration(config, tmp_path)
    [(path, loaded)] = list_configurations(tmp_path)

    assert path.parent == tmp_path
    assert loaded.pack.name == "Drum Kit"
    assert loaded.pack.description == "A test kit"
    assert loaded.pack.created_at == created
    assert loaded.pack.modified_at == modified
    assert loaded.assignments == {
        ("A", "1"): "/samples/kick.wav",
        ("B", "3"): "/samples/snare.wav",
    }
    assert loaded.pack.holding == ["/samples/tom.wav", "/samples/clap.wav"]


def test_holding_defaults_to_empty_list_when_absent_from_saved_json(tmp_path):
    # Configurations saved before "holding" existed have no such key at
    # all in their JSON, not an empty one - list_configurations must
    # still load them rather than raising a KeyError.
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(name="Old Kit", description="", created_at=now, modified_at=now)
    )
    save_configuration(config, tmp_path)

    path = next(tmp_path.glob("*.json"))
    data = json.loads(path.read_text())
    del data["holding"]
    path.write_text(json.dumps(data))

    [(_, loaded)] = list_configurations(tmp_path)
    assert loaded.pack.holding == []


def test_filename_derived_from_slugified_name(tmp_path):
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(name="My Drum Kit!", description="", created_at=now, modified_at=now)
    )

    path = save_configuration(config, tmp_path)

    assert path == tmp_path / "my-drum-kit.json"


def test_name_collision_gets_a_numeric_suffix(tmp_path):
    now = datetime(2026, 1, 1)
    first = Configuration(pack=Pack(name="Kit", description="", created_at=now, modified_at=now))
    second = Configuration(
        pack=Pack(name="Kit", description="", created_at=now, modified_at=now)
    )

    path1 = save_configuration(first, tmp_path)
    path2 = save_configuration(second, tmp_path)

    assert path1 == tmp_path / "kit.json"
    assert path2 == tmp_path / "kit-2.json"
    assert len(list_configurations(tmp_path)) == 2


def test_list_from_missing_directory_is_empty(tmp_path):
    assert list_configurations(tmp_path / "does-not-exist") == []


def test_list_skips_corrupt_files_rather_than_crashing(tmp_path):
    now = datetime(2026, 1, 1)
    good = Configuration(
        pack=Pack(name="Good", description="", created_at=now, modified_at=now)
    )
    save_configuration(good, tmp_path)
    (tmp_path / "corrupt.json").write_text("{not valid json")
    (tmp_path / "wrong-shape.json").write_text(json.dumps({"unexpected": "shape"}))

    results = list_configurations(tmp_path)

    assert len(results) == 1
    assert results[0][1].pack.name == "Good"


def test_delete_removes_the_file(tmp_path):
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(name="Kit", description="", created_at=now, modified_at=now)
    )
    path = save_configuration(config, tmp_path)

    delete_configuration(path)

    assert not path.exists()
    assert list_configurations(tmp_path) == []


def test_delete_missing_file_does_not_raise(tmp_path):
    delete_configuration(tmp_path / "does-not-exist.json")


def test_export_holding_copies_every_held_file_into_a_named_subfolder(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    kick = source_dir / "kick.wav"
    snare = source_dir / "snare.wav"
    kick.write_bytes(b"kick-data")
    snare.write_bytes(b"snare-data")
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(
            name="My Kit",
            description="",
            created_at=now,
            modified_at=now,
            holding=[str(kick), str(snare)],
        )
    )
    root = tmp_path / "export"

    result = export_holding(config, root)

    assert result.exported == 2
    assert result.missing == []
    assert result.destination == root / "my-kit"
    assert (root / "my-kit" / "kick.wav").read_bytes() == b"kick-data"
    assert (root / "my-kit" / "snare.wav").read_bytes() == b"snare-data"


def test_export_holding_slugifies_the_configuration_name_for_the_folder(tmp_path):
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(name="My Drum Kit!", description="", created_at=now, modified_at=now)
    )

    result = export_holding(config, tmp_path)

    assert result.destination == tmp_path / "my-drum-kit"


def test_export_holding_skips_and_reports_missing_sources(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    kick = source_dir / "kick.wav"
    kick.write_bytes(b"kick-data")
    gone = source_dir / "gone.wav"  # never actually created
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(
            name="Kit",
            description="",
            created_at=now,
            modified_at=now,
            holding=[str(kick), str(gone)],
        )
    )

    result = export_holding(config, tmp_path)

    assert result.exported == 1
    assert result.missing == [str(gone)]
    assert (result.destination / "kick.wav").exists()


def test_export_holding_disambiguates_same_named_files_from_different_folders(tmp_path):
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    folder_a.mkdir()
    folder_b.mkdir()
    kick_a = folder_a / "kick.wav"
    kick_b = folder_b / "kick.wav"
    kick_a.write_bytes(b"from-a")
    kick_b.write_bytes(b"from-b")
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(
            name="Kit",
            description="",
            created_at=now,
            modified_at=now,
            holding=[str(kick_a), str(kick_b)],
        )
    )

    result = export_holding(config, tmp_path)

    assert result.exported == 2
    assert (result.destination / "kick.wav").read_bytes() == b"from-a"
    assert (result.destination / "kick-2.wav").read_bytes() == b"from-b"


def test_export_holding_creates_the_destination_folder(tmp_path):
    kick = tmp_path / "kick.wav"
    kick.write_bytes(b"kick-data")
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(
            name="Kit",
            description="",
            created_at=now,
            modified_at=now,
            holding=[str(kick)],
        )
    )
    root = tmp_path / "does" / "not" / "exist-yet"

    result = export_holding(config, root)

    assert (result.destination / "kick.wav").exists()
