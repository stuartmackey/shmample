import json
from datetime import datetime

from shmample.config_store import (
    Configuration,
    delete_configuration,
    list_configurations,
    save_configuration,
)


def test_save_and_list_round_trips_all_fields(tmp_path):
    created = datetime(2026, 1, 1, 12, 0, 0)
    modified = datetime(2026, 1, 2, 9, 30, 0)
    config = Configuration(
        name="Drum Kit",
        description="A test kit",
        created_at=created,
        modified_at=modified,
        assignments={("A", "1"): "/samples/kick.wav", ("B", "3"): "/samples/snare.wav"},
        holding=["/samples/tom.wav", "/samples/clap.wav"],
    )

    save_configuration(config, tmp_path)
    [(path, loaded)] = list_configurations(tmp_path)

    assert path.parent == tmp_path
    assert loaded.name == "Drum Kit"
    assert loaded.description == "A test kit"
    assert loaded.created_at == created
    assert loaded.modified_at == modified
    assert loaded.assignments == {
        ("A", "1"): "/samples/kick.wav",
        ("B", "3"): "/samples/snare.wav",
    }
    assert loaded.holding == ["/samples/tom.wav", "/samples/clap.wav"]


def test_holding_defaults_to_empty_list_when_absent_from_saved_json(tmp_path):
    # Configurations saved before "holding" existed have no such key at
    # all in their JSON, not an empty one - list_configurations must
    # still load them rather than raising a KeyError.
    now = datetime(2026, 1, 1)
    config = Configuration(name="Old Kit", description="", created_at=now, modified_at=now)
    save_configuration(config, tmp_path)

    path = next(tmp_path.glob("*.json"))
    data = json.loads(path.read_text())
    del data["holding"]
    path.write_text(json.dumps(data))

    [(_, loaded)] = list_configurations(tmp_path)
    assert loaded.holding == []


def test_filename_derived_from_slugified_name(tmp_path):
    now = datetime(2026, 1, 1)
    config = Configuration(name="My Drum Kit!", description="", created_at=now, modified_at=now)

    path = save_configuration(config, tmp_path)

    assert path == tmp_path / "my-drum-kit.json"


def test_name_collision_gets_a_numeric_suffix(tmp_path):
    now = datetime(2026, 1, 1)
    first = Configuration(name="Kit", description="", created_at=now, modified_at=now)
    second = Configuration(name="Kit", description="", created_at=now, modified_at=now)

    path1 = save_configuration(first, tmp_path)
    path2 = save_configuration(second, tmp_path)

    assert path1 == tmp_path / "kit.json"
    assert path2 == tmp_path / "kit-2.json"
    assert len(list_configurations(tmp_path)) == 2


def test_list_from_missing_directory_is_empty(tmp_path):
    assert list_configurations(tmp_path / "does-not-exist") == []


def test_list_skips_corrupt_files_rather_than_crashing(tmp_path):
    now = datetime(2026, 1, 1)
    good = Configuration(name="Good", description="", created_at=now, modified_at=now)
    save_configuration(good, tmp_path)
    (tmp_path / "corrupt.json").write_text("{not valid json")
    (tmp_path / "wrong-shape.json").write_text(json.dumps({"unexpected": "shape"}))

    results = list_configurations(tmp_path)

    assert len(results) == 1
    assert results[0][1].name == "Good"


def test_delete_removes_the_file(tmp_path):
    now = datetime(2026, 1, 1)
    config = Configuration(name="Kit", description="", created_at=now, modified_at=now)
    path = save_configuration(config, tmp_path)

    delete_configuration(path)

    assert not path.exists()
    assert list_configurations(tmp_path) == []


def test_delete_missing_file_does_not_raise(tmp_path):
    delete_configuration(tmp_path / "does-not-exist.json")
