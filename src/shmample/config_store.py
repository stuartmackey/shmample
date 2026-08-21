import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIGURATIONS_DIR = Path.home() / ".config" / "shmample" / "configurations"


@dataclass
class Configuration:
    name: str
    description: str
    created_at: datetime
    modified_at: datetime
    # (bank, pad) -> original sample filepath, per 02-implementation-plan.md
    assignments: dict[tuple[str, str], str] = field(default_factory=dict)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "configuration"


def _to_json(config: Configuration) -> dict:
    return {
        "name": config.name,
        "description": config.description,
        "created_at": config.created_at.isoformat(),
        "modified_at": config.modified_at.isoformat(),
        "assignments": [
            {"bank": bank, "pad": pad, "sample_path": sample_path}
            for (bank, pad), sample_path in config.assignments.items()
        ],
    }


def _from_json(data: dict) -> Configuration:
    return Configuration(
        name=data["name"],
        description=data.get("description", ""),
        created_at=datetime.fromisoformat(data["created_at"]),
        modified_at=datetime.fromisoformat(data["modified_at"]),
        assignments={
            (entry["bank"], entry["pad"]): entry["sample_path"]
            for entry in data.get("assignments", [])
        },
    )


def list_configurations(
    directory: Path = DEFAULT_CONFIGURATIONS_DIR,
) -> list[tuple[Path, Configuration]]:
    """Configurations found in `directory`, paired with their file path.

    No parent index file (settled in 06-configuration-list.md) - just
    reads whatever's there. Skips any file that fails to parse rather
    than crashing the pane over one bad/corrupt file.
    """
    if not directory.is_dir():
        return []
    results = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            results.append((path, _from_json(data)))
        except (json.JSONDecodeError, KeyError, OSError, ValueError):
            continue
    return results


def save_configuration(
    config: Configuration,
    directory: Path = DEFAULT_CONFIGURATIONS_DIR,
    path: Path | None = None,
) -> Path:
    """Writes `config` as JSON. If `path` isn't given (a new configuration),
    derives a filename from its name, disambiguating on collision."""
    directory.mkdir(parents=True, exist_ok=True)
    if path is None:
        slug = _slugify(config.name)
        path = directory / f"{slug}.json"
        counter = 2
        while path.exists():
            path = directory / f"{slug}-{counter}.json"
            counter += 1
    path.write_text(json.dumps(_to_json(config), indent=2))
    return path


def delete_configuration(path: Path) -> None:
    path.unlink(missing_ok=True)
