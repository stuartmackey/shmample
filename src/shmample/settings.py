import json
from dataclasses import dataclass, field
from pathlib import Path

SETTINGS_PATH = Path.home() / ".config" / "shmample" / "settings.json"


@dataclass
class Settings:
    # Ordered (not a set) and de-duplicated by the caller (see
    # FileBrowser.action_add_samples_directory) - the order configured
    # roots were added in is also the order they appear in the tree.
    samples_directories: list[Path] = field(default_factory=list)


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    if not path.exists():
        return Settings()
    data = json.loads(path.read_text())
    return Settings(samples_directories=[Path(p) for p in data.get("samples_directories", [])])


def save_settings(settings: Settings, path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"samples_directories": [str(p) for p in settings.samples_directories]}
    path.write_text(json.dumps(data, indent=2))
