import json
from pathlib import Path

from shmample.settings import Settings, load_settings, save_settings


def test_load_settings_with_no_file_returns_empty_directories(tmp_path):
    settings = load_settings(tmp_path / "settings.json")
    assert settings.samples_directories == []


def test_save_then_load_round_trips_multiple_directories(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(samples_directories=[Path("/a/b"), Path("/c/d")]), path)

    loaded = load_settings(path)

    assert loaded.samples_directories == [Path("/a/b"), Path("/c/d")]


def test_load_settings_with_no_file_returns_empty_directory_aliases(tmp_path):
    settings = load_settings(tmp_path / "settings.json")
    assert settings.directory_aliases == {}


def test_save_then_load_round_trips_directory_aliases(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(
        Settings(
            samples_directories=[Path("/a/b")],
            directory_aliases={Path("/a/b"): "Drums"},
        ),
        path,
    )

    loaded = load_settings(path)

    assert loaded.directory_aliases == {Path("/a/b"): "Drums"}


def test_load_settings_without_directory_aliases_key_defaults_to_empty(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"samples_directories": ["/a/b"]}))

    loaded = load_settings(path)

    assert loaded.samples_directories == [Path("/a/b")]
    assert loaded.directory_aliases == {}
