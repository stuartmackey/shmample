import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIGURATIONS_DIR = Path.home() / ".config" / "shmample" / "configurations"


@dataclass
class Pack:
    """The device-agnostic half of a saved configuration: the named group
    of samples a user has collected, before any of it is placed onto a
    specific device's layout. Split out from `Configuration` (see
    03-handling-multiple-devices.md) so a later task can give a pack a
    one-to-many relationship with per-device configurations without
    reshaping this part again."""

    name: str
    description: str
    created_at: datetime
    modified_at: datetime
    # Ordered, device-agnostic staging list of sample filepaths "in" this
    # pack but not yet (or not ever) tied to a specific device's bank/pad
    # layout - the first step towards decoupling a configuration from any
    # one device's shape. Unique by path - re-adding an already-held
    # sample is a no-op (see HoldingArea.add_samples), not a second entry.
    holding: list[str] = field(default_factory=list)


@dataclass
class Configuration:
    pack: Pack
    # (bank, pad) -> original sample filepath, per 02-implementation-plan.md
    assignments: dict[tuple[str, str], str] = field(default_factory=dict)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "configuration"


def _to_json(config: Configuration) -> dict:
    return {
        "name": config.pack.name,
        "description": config.pack.description,
        "created_at": config.pack.created_at.isoformat(),
        "modified_at": config.pack.modified_at.isoformat(),
        "assignments": [
            {"bank": bank, "pad": pad, "sample_path": sample_path}
            for (bank, pad), sample_path in config.assignments.items()
        ],
        "holding": list(config.pack.holding),
    }


def _from_json(data: dict) -> Configuration:
    pack = Pack(
        name=data["name"],
        description=data.get("description", ""),
        created_at=datetime.fromisoformat(data["created_at"]),
        modified_at=datetime.fromisoformat(data["modified_at"]),
        # .get(..., []) - configurations saved before "holding" existed
        # have no such key at all, not an empty one.
        holding=list(data.get("holding", [])),
    )
    return Configuration(
        pack=pack,
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
        slug = _slugify(config.pack.name)
        path = directory / f"{slug}.json"
        counter = 2
        while path.exists():
            path = directory / f"{slug}-{counter}.json"
            counter += 1
    path.write_text(json.dumps(_to_json(config), indent=2))
    return path


def delete_configuration(path: Path) -> None:
    path.unlink(missing_ok=True)


def remove_samples_under(root: Path, directory: Path = DEFAULT_CONFIGURATIONS_DIR) -> int:
    """Strips every held/assigned sample at or under `root` from every saved
    pack in `directory` - used when a samples directory is removed (see
    FileBrowser.action_remove_samples_directory) so a pack doesn't keep
    pointing at paths that no longer exist. Only the affected entries are
    dropped - the rest of a touched pack (and every other pack) is left
    untouched. Returns the number of packs actually modified."""
    updated = 0
    for path, config in list_configurations(directory):
        held = [p for p in config.pack.holding if not Path(p).is_relative_to(root)]
        assignments = {
            key: value
            for key, value in config.assignments.items()
            if not Path(value).is_relative_to(root)
        }
        if len(held) == len(config.pack.holding) and len(assignments) == len(config.assignments):
            continue
        config.pack.holding = held
        config.assignments = assignments
        config.pack.modified_at = datetime.now()
        save_configuration(config, directory, path)
        updated += 1
    return updated


@dataclass
class ExportResult:
    exported: int
    missing: list[str]
    destination: Path


def export_holding(configuration: Configuration, root: Path) -> ExportResult:
    """Copies every held sample in `configuration` as a plain file into
    `root`/<slugified configuration name>/ - the simplest way to get a
    configuration's held samples out for use in other systems, with none
    of device.send_configuration's P-6-specific bank/pad structure (or
    its fsync durability paranoia, which exists only for removable
    device media, not a plain host folder).

    Nested under the configuration's own name (not dumped straight into
    `root`) so exporting more than one configuration into the same
    chosen folder over time doesn't mix their samples together - each
    export is self-contained and identifiable by its folder name.
    Slugified, same as save_configuration's own filename, so the name's
    free-text origin (typed into NewConfigurationModal, no character
    restrictions) can't produce a path separator or other filesystem-
    unsafe folder name.

    A source that's gone missing since being held is skipped and
    reported back rather than aborting the whole export over one bad
    file, same reasoning as send_configuration's own `missing` list. A
    same-named collision inside that folder (e.g. two held samples both
    called "kick.wav", from different source folders) is disambiguated
    with a numeric suffix, the same scheme save_configuration uses for a
    configuration's own filename - never silently overwritten.
    """
    target = root / _slugify(configuration.pack.name)
    target.mkdir(parents=True, exist_ok=True)
    exported = 0
    missing: list[str] = []
    for sample_path in configuration.pack.holding:
        source = Path(sample_path)
        if not source.is_file():
            missing.append(sample_path)
            continue

        dest = target / source.name
        counter = 2
        while dest.exists():
            dest = target / f"{source.stem}-{counter}{source.suffix}"
            counter += 1
        shutil.copy2(source, dest)
        exported += 1
    return ExportResult(exported=exported, missing=missing, destination=target)
