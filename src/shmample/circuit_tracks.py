"""Direct SD-card export to a Novation Circuit Tracks (CT).

Writes a held pack straight onto a CT's microSD card as a plain
`Tracks/<NN>_<name>/{meta/00_META.ncm, PCM/*.wav}` folder - the layout
reverse-engineered by hand in docs/tasks/04-export-to-ct.md's round 3/5
notes, and confirmed end-to-end on real hardware (Novation Components
recognised a hand-written pack, and the CT itself loaded and played it).

CT pack slots are numbered 1-32 on the device, but slot 1 is the
internal-only "Waves" kit baked into flash - it has no SD-card folder at
all and can only ever be reached over MIDI SysEx (round 4's findings, not
implemented here - see the task doc's "Scope decision"). Only slots 2-32,
each a numbered folder under `Tracks/` (folder number = pack_index - 2),
are reachable this way.
"""

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from shmample import device
from shmample.config_store import Configuration

TRACKS_DIRNAME = "Tracks"

MIN_PACK_INDEX = 2
MAX_PACK_INDEX = 32

# A real zero-Sessions pack's meta/00_META.ncm is exactly these two bytes
# (confirmed by reading several factory sample-only packs off a real
# card) - there's no documented meaning beyond "present and this size".
META_FILENAME = "00_META.ncm"
META_CONTENT = b"\x00\x00"

_FOLDER_RE = re.compile(r"^(\d{2})_(.+)$")
_INVALID_FAT32_CHARS = re.compile(r'[\\/:*?"<>|]')


def _folder_number(pack_index: int) -> int:
    return pack_index - MIN_PACK_INDEX


def _fat32_safe(name: str) -> str:
    """Strips characters FAT32 long filenames can't store - every pack
    folder/sample name observed on a real card avoids exactly this set."""
    cleaned = _INVALID_FAT32_CHARS.sub("", name).strip().strip(".")
    return cleaned or "Pack"


def find_ct_cards() -> list[Path]:
    """Every currently-mounted volume that looks like a CT SD card - has
    a `Tracks` folder at its root, the one structural marker every real
    card has (there's no predictable volume label to search by, unlike
    the P-6's "P-6" label). Reuses device.candidate_mount_roots' generic
    OS-level scan of removable-media locations (it isn't actually P-6-
    specific itself - the P-6 name-filtering happens later, in
    autodetect_mount) rather than duplicating that platform-branching
    logic here."""
    return [
        root
        for root in device.candidate_mount_roots()
        if device._safe_is_dir(root) and device._safe_is_dir(root / TRACKS_DIRNAME)
    ]


def is_writable(mount: Path) -> bool:
    """Whether `mount` can actually be written to - a cheap pre-flight
    check so a read-only-mounted card (a real, repeatedly-hit issue with
    CT SD cards specifically, per docs/tasks/04-export-to-ct.md's round
    3/5 notes - a faulty adapter or a stale mount can both leave a card
    mounted `ro`) fails with a clear message before ever reaching the
    pack-slot picker, rather than crashing partway through a real write."""
    return os.access(mount, os.W_OK)


@dataclass
class PackSlot:
    """One of the CT's 31 SD-card pack slots (device Packs 2-32)."""

    index: int
    folder: Path | None  # existing folder for this slot, or None if empty
    name: str | None  # existing pack's display name, or None if empty

    @property
    def occupied(self) -> bool:
        return self.folder is not None


def list_pack_slots(mount: Path) -> list[PackSlot]:
    """Every CT pack slot 2-32, flagging which already have content - by
    scanning `mount`/Tracks for `NN_Name` folders exactly as the device
    itself lays them out, not over MIDI. A missing/not-yet-created
    `Tracks` folder (a freshly formatted card) just means every slot
    comes back empty, not an error - and so does a single entry that
    can't be stat'd (real removable-media flakiness observed on actual
    hardware: an intermittent I/O error reading one folder's metadata
    while every other entry on the same card read fine), skipped rather
    than crashing the whole listing over one bad entry."""
    tracks_root = mount / TRACKS_DIRNAME
    existing: dict[int, tuple[Path, str]] = {}
    if tracks_root.is_dir():
        try:
            entries = list(tracks_root.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            match = _FOLDER_RE.match(entry.name)
            if match is None:
                continue
            existing[int(match.group(1))] = (entry, match.group(2))

    slots = []
    for index in range(MIN_PACK_INDEX, MAX_PACK_INDEX + 1):
        folder, name = existing.get(_folder_number(index), (None, None))
        slots.append(PackSlot(index=index, folder=folder, name=name))
    return slots


@dataclass
class CtExportResult:
    exported: int
    missing: list[str]
    destination: Path


def send_pack_to_slot(configuration: Configuration, mount: Path, pack_index: int) -> CtExportResult:
    """Writes `configuration`'s held samples as a new pack folder at
    `pack_index` (2-32), in holding order (`00_`, `01_`, ...), replacing
    whatever's already in that slot entirely.

    Mirrors device.py's send_configuration durability pattern (explicit
    fsync of every written file, then of the directory chain up to
    `mount`) rather than export_holding's plain-copy approach, since this
    is removable device media the CT itself reads from next - see
    send_configuration's own docstring for why a plain copy isn't durable
    enough for that.

    Unlike send_configuration (which only clears files, preserving
    existing folder structure the device may care about), the whole slot
    folder is removed and recreated here - a pack slot is being fully
    replaced, not selectively updated, so there's nothing existing worth
    preserving.
    """
    if not MIN_PACK_INDEX <= pack_index <= MAX_PACK_INDEX:
        raise ValueError(f"pack_index must be {MIN_PACK_INDEX}-{MAX_PACK_INDEX}, got {pack_index}")

    tracks_root = mount / TRACKS_DIRNAME
    tracks_root.mkdir(parents=True, exist_ok=True)

    for slot in list_pack_slots(mount):
        if slot.index == pack_index and slot.folder is not None:
            shutil.rmtree(slot.folder)
            break

    folder_name = f"{_folder_number(pack_index):02d}_{_fat32_safe(configuration.pack.name)}"
    pack_dir = tracks_root / folder_name
    meta_dir = pack_dir / "meta"
    pcm_dir = pack_dir / "PCM"
    meta_dir.mkdir(parents=True)
    pcm_dir.mkdir(parents=True)

    meta_path = meta_dir / META_FILENAME
    meta_path.write_bytes(META_CONTENT)
    device._fsync_up_to(meta_path, mount)

    exported = 0
    missing: list[str] = []
    for i, sample_path in enumerate(configuration.pack.holding):
        source = Path(sample_path)
        if not source.is_file():
            missing.append(sample_path)
            continue
        dest = pcm_dir / f"{i:02d}_{_fat32_safe(source.name)}"
        shutil.copy2(source, dest)
        device._fsync_up_to(dest, mount)
        exported += 1

    device._fsync_up_to(pack_dir, mount)
    return CtExportResult(exported=exported, missing=missing, destination=pack_dir)
