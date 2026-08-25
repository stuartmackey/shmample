"""Detecting whether a P-6 is connected and which mode it's mounted in.

Ported from p6-lab's p6backup/p6tool/config.py + device.py (a sibling
project with a working CLI for this exact device) rather than imported -
shmample stays self-contained, no dependency on that other project. The
CLI's blocking input()/print() prompt loop isn't ported at all; a TUI
polls/displays state instead of blocking on it.
"""

import asyncio
import json
import os
import platform
import re
import shutil
import string
from dataclasses import dataclass
from pathlib import Path

from shmample.config_store import Configuration
from shmample.waveform import get_duration_seconds, get_format_info

BANK_LETTERS = "ABCDEFGH"
# The device only has 4 physical bank buttons, not 8 - each one toggles
# between two banks (A/E, B/F, C/G, D/H), so e.g. BANK_A and BANK_E are
# reached via the same button. Grouping banks by that pairing rather than
# alphabetically puts each button's two banks next to each other, which
# is more useful for eyeballing/organising samples than A..H in a row.
BANK_DISPLAY_ORDER = "AEBFCGDH"
PAD_NUMBERS = range(1, 7)
PATTERN_GROUPS = range(1, 5)
PATTERN_NUMBERS = range(1, 17)
EXPECTED_PATTERN_COUNT = len(PATTERN_GROUPS) * len(PATTERN_NUMBERS)

# The mode is entirely determined by which one of these folder names is
# present at the mount root - the device only ever exposes one at a time,
# chosen by a button combo held at power-on. Confirmed against p6-lab's
# actual copy logic: pattern files sit directly under BACKUP/RESTORE (no
# nested "patterns" subfolder on the device itself - that nesting only
# exists in p6-lab's own local backup archive layout).
MODE_IMPORT = "IMPORT"  # sample import: IMPORT/BANK_A..H/PAD_1..6/
MODE_EXPORT = "EXPORT"  # sample export: EXPORT/BANK_X/PAD_Y/*.WAV, *.PRM (one bank at a time)
MODE_BACKUP = "BACKUP"  # pattern export: BACKUP/P6_PTN1-01.PRM ... P6_PTN4-16.PRM
MODE_RESTORE = "RESTORE"  # pattern import: RESTORE/P6_PTN*.PRM

ALL_MODES = (MODE_IMPORT, MODE_EXPORT, MODE_BACKUP, MODE_RESTORE)

# Shown to the user when a send is requested but the device isn't
# currently mounted in MODE_IMPORT - matches p6-lab's own send.py wording
# for the same situation.
IMPORT_MODE_INSTRUCTIONS = "Power-cycle the P-6 into sample-import mode so it mounts with an IMPORT folder."


def bank_folder(letter: str) -> str:
    return f"BANK_{letter}"


def pad_folder(number: int) -> str:
    return f"PAD_{number}"


def pattern_filenames():
    """Every pattern filename the device can produce, e.g. P6_PTN1-01.PRM."""
    for group in PATTERN_GROUPS:
        for number in PATTERN_NUMBERS:
            yield f"P6_PTN{group}-{number:02d}.PRM"


@dataclass
class SendResult:
    """Outcome of send_configuration - how many samples actually got
    copied, plus the original (not-a-Path-any-more) sample_path strings
    for any assignment whose source file no longer exists. Missing
    sources aren't fatal - ported from p6-lab's send.py, which reports
    and skips a missing file rather than aborting the whole batch."""

    sent: int
    missing: list[str]


def _fsync_path(path: Path) -> None:
    """fsync a file or directory. A newly created (or removed) entry's
    *directory* needs its own fsync, separate from a file's own content
    fsync, or a crash/power-cycle before that lands can lose the entry
    even though the file's content made it to disk - see
    send_configuration's docstring for the real bug this exists to fix.

    Windows has no O_DIRECTORY to open a directory with in the first
    place - skipped there rather than raising, same "this platform
    quirk doesn't exist here" reasoning as candidate_mount_roots' own
    platform branches above.
    """
    if platform.system() == "Windows":
        return
    flags = os.O_RDONLY | (os.O_DIRECTORY if path.is_dir() else 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_up_to(leaf: Path, root: Path) -> None:
    """fsync `leaf` and every directory between it and (inclusive of)
    `root` - see _fsync_path for why a file's own content fsync alone
    isn't enough to make a new file/folder durable."""
    current = leaf
    while True:
        _fsync_path(current)
        if current == root:
            break
        current = current.parent


def send_configuration(configuration: Configuration, mount: Path) -> SendResult:
    """Copies every assigned sample in `configuration` onto `mount`'s
    IMPORT/BANK_x/PAD_y/ - one file per pad, matching p6-lab's send.py.

    IMPORT is a one-way staging area, not a live view of the device's
    actual sample memory - there's no way to see via USB what's currently
    loaded on a pad (that's what EXPORT is for, one bank at a time), so
    whatever's already sitting there is just leftover staged data, ours
    or otherwise (in practice this turns out to include the device's
    factory-default demo kit, which ships already staged and apparently
    never auto-clears), not "the current sample on that pad".

    That leftover data does real damage though: IMPORT is a fixed, tiny
    (~10MB observed) partition, and every send used to only clear the
    *specific* pads it was about to (re)write - so anything else stayed
    there forever, silently eating the whole budget until nothing new
    fit at all (see check_available_space and 09-save-assignments.md's
    "not sure how to get this to work" report). Since none of it
    represents anything worth preserving, every existing *file* anywhere
    under IMPORT is removed up front, not just the pads this
    configuration assigns.

    Deliberately only files, not directories: an earlier version of this
    also `shutil.rmtree`'d and recreated the whole BANK_x/PAD_y tree, on
    the theory that clearing space was enough - reverted after a report
    that samples still weren't being picked up, on the (untested but
    plausible, and cheap to rule out by just not doing it) theory that
    recreating directories on the device's own FAT-formatted volume
    loses attributes/permissions the factory-original folders had that a
    plain host-side `mkdir` doesn't replicate. `mkdir(exist_ok=True)`
    below is a no-op for any folder that already exists (leaving it, and
    whatever the device cares about on it, completely untouched) and
    only creates one that's genuinely missing.

    Every write is followed by an explicit fsync (file *and* the
    directory chain up to `mount`) - a real report against actual
    hardware showed why this matters: `shutil.copy2` alone only
    guarantees data reaches the OS's page cache, not the physical
    medium. Removable USB media that gets power-cycled (rather than
    cleanly unmounted first) can lose exactly the writes still sitting
    in that cache - which looked, from the outside, like "the files are
    in place" (a plain `ls` reads the cache same as anything else) right
    up until the device was power-cycled and remounted with some pads
    empty and the rest untouched by the "import".
    """
    import_root = mount / MODE_IMPORT
    if import_root.is_dir():
        for existing in import_root.rglob("*"):
            if existing.is_file():
                existing.unlink()

    sent = 0
    missing: list[str] = []
    for (bank, pad), sample_path in sorted(configuration.assignments.items()):
        source = Path(sample_path)
        if not source.is_file():
            missing.append(sample_path)
            continue

        pad_dir = import_root / bank_folder(bank) / pad_folder(int(pad))
        pad_dir.mkdir(parents=True, exist_ok=True)
        dest = pad_dir / source.name
        shutil.copy2(source, dest)
        _fsync_path(dest)
        _fsync_up_to(pad_dir, mount)
        sent += 1

    # Covers the case the loop above never ran at all (nothing assigned,
    # or every source was missing) - the rmtree/recreate of IMPORT
    # itself still needs its entry in `mount` made durable even then.
    # Guarded on is_dir() rather than assumed - a real, connected device
    # always has a real mount point, but callers with nothing to send
    # (e.g. a bare Path in a test) may pass one that was never created.
    if mount.is_dir():
        _fsync_path(mount)
    return SendResult(sent=sent, missing=missing)


def human_bytes(num_bytes: int) -> str:
    """1234567 -> "1.2MB" - ported from p6-lab's fsutil.human_size."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}GB"


@dataclass
class SpaceCheck:
    """Outcome of check_available_space - whether a send would fit, plus
    the numbers involved (for reporting a useful "needs X, only Y
    available" warning rather than a bare yes/no).

    Both fields describe the *same* moment - right after
    send_configuration's whole-tree wipe, just before it starts copying -
    not a mix of "net of what'll be freed" and "raw right now". Comparing
    a pre-wipe free_bytes against a post-wipe-credited needed_bytes would
    make an easily-fixable "just needs the stale tree cleared" case look
    identical to a genuine "this configuration is bigger than the device
    can ever hold" case - the two need different framing to the user
    (one's this tool's problem, the other's a hardware ceiling), which
    isn't possible if the numbers themselves aren't on the same basis.
    """

    fits: bool
    needed_bytes: int
    free_bytes: int


def configuration_size_bytes(configuration: Configuration) -> int:
    """Total size of every assigned sample that still exists - the same
    total send_configuration will actually try to copy. Missing sources
    contribute nothing, same as send_configuration/check_available_space
    below (both build on this)."""
    return sum(
        Path(sample_path).stat().st_size
        for sample_path in configuration.assignments.values()
        if Path(sample_path).is_file()
    )


def available_bytes_once_cleared(mount: Path) -> int:
    """What a send onto `mount` would actually have to work with - its
    current free space, plus whatever its existing IMPORT tree's files
    are holding, since send_configuration removes every one of them
    before copying anything in (see its docstring - the folders
    themselves are left alone, only their contents are cleared).
    Shared by check_available_space (compares one configuration's size
    against this) and ConfigList's per-row size colouring (compares
    every listed configuration's size against this same number, computed
    once per refresh rather than once per row).
    """
    import_root = mount / MODE_IMPORT
    reclaimable = 0
    if import_root.is_dir():
        reclaimable = sum(f.stat().st_size for f in import_root.rglob("*") if f.is_file())
    return shutil.disk_usage(mount).free + reclaimable


def check_available_space(configuration: Configuration, mount: Path) -> SpaceCheck:
    """Whether sending `configuration` would fit in `mount`'s actual free
    space - this, not the per-pad audio-time limit truncation_risks looks
    for below, is what an "out of space" failure during a send actually
    is: IMPORT is a real (if small - ~10MB observed) mass-storage volume,
    and send_configuration above just does plain file copies onto it, so
    it fails exactly the way any other too-big-for-the-disk copy would.

    `needed_bytes` is configuration_size_bytes - the plain total of every
    assignment whose source still exists. `free_bytes` is
    available_bytes_once_cleared - what would be available right after
    send_configuration clears every existing file under IMPORT, not the
    mount's raw free space right now. If needed_bytes still exceeds
    free_bytes even measured this way, the configuration genuinely
    doesn't fit on this device - no amount of clearing stale content
    changes that.
    """
    needed = configuration_size_bytes(configuration)
    free = available_bytes_once_cleared(mount)
    return SpaceCheck(fits=needed <= free, needed_bytes=needed, free_bytes=free)


# The manual (docs/reference/P-6_eng01_W (5)_compressed.pdf, "Main
# specifications", p.151) only
# publishes maximum sample time as four mono-at-a-specific-rate figures
# (5.9s @ 44.1kHz, 11.8s @ 22.05kHz, 17.8s @ 14.7kHz, 23.7s @ 11.025kHz;
# half that for stereo) rather than a per-pad byte figure - but each one
# multiplies out to the same ~520KB at 16-bit (e.g. 5.9 * 44100 * 2 =
# 520380), so that's treated here as a fixed per-pad memory budget rather
# than reproducing the table's four discrete rows, which generalises to
# any imported file's own rate/channel count rather than just the four
# rates the device itself records at.
#
# The manual also says available import time "varies with sample rate
# AND bit rate", but publishes no figures for anything other than the
# implied-16-bit rows above - there's no documented number to build a
# bit-depth adjustment from, so this assumes the device stores everything
# internally at 16-bit regardless of an imported file's own bit depth.
# Best-effort, not a device-verified constant - see 09-save-assignments.md.
PAD_MEMORY_BUDGET_BYTES = round(5.9 * 44_100 * 2)


@dataclass
class TruncationRisk:
    """One assignment whose sample looks too long for its pad at its own
    sample rate/channel count - see truncation_risks below."""

    bank: str
    pad: str
    sample_path: str
    actual_seconds: float
    max_seconds: float


def truncation_risks(configuration: Configuration) -> list[TruncationRisk]:
    """Assignments likely to come back shorter than expected once the
    device actually imports them - per the manual, oversized sample data
    "is truncated" on import, silently and without error, so this is the
    only way a user finds out beforehand rather than after listening back
    to a cut-off sample.

    Best-effort: needs the file's own sample rate and channel count (from
    its WAV header, via waveform.get_format_info) - a source that's
    missing or unreadable is skipped here rather than flagged, since
    send_configuration's own missing-source handling already covers that
    case with a harder, more specific warning.
    """
    risks = []
    for (bank, pad), sample_path in sorted(configuration.assignments.items()):
        source = Path(sample_path)
        info = get_format_info(source)
        duration = get_duration_seconds(source)
        if info is None or duration is None or info.frame_rate <= 0 or info.channels <= 0:
            continue
        max_seconds = PAD_MEMORY_BUDGET_BYTES / (info.frame_rate * info.channels * 2)
        if duration > max_seconds:
            risks.append(TruncationRisk(bank, pad, sample_path, duration, max_seconds))
    return risks


def _subdirs(path: Path) -> list[Path]:
    """Immediate subdirectories of path, or [] if unreadable/missing."""
    try:
        return sorted(p for p in path.iterdir() if p.is_dir())
    except OSError:
        return []


def candidate_mount_roots() -> list[Path]:
    """Plausible places the P-6 might show up, without requiring it to
    already be mounted - just directories worth checking.

    Linux mount managers nest the drive under a per-user folder (e.g.
    /run/media/<user>/P-6), but the username isn't always available from
    the environment, so this scans two levels deep under each base
    instead of trying to guess it - same reasoning as p6-lab's version.
    """
    system = platform.system()
    candidates: list[Path] = []

    if system == "Darwin":
        base = Path("/Volumes")
        candidates.append(base / "P-6")
        candidates.extend(_subdirs(base))
    elif system == "Windows":
        candidates.extend(Path(f"{letter}:\\") for letter in string.ascii_uppercase)
    else:
        for base in (Path("/run/media"), Path("/media"), Path("/mnt")):
            candidates.append(base / "P-6")
            for entry in _subdirs(base):
                candidates.append(entry)
                candidates.append(entry / "P-6")
                candidates.extend(_subdirs(entry))

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _safe_is_dir(path: Path) -> bool:
    """Like Path.is_dir(), but treats a permission error as "no" instead of
    raising - e.g. a root-owned lost+found left behind once whatever used to
    be mounted over it (a previously-added samples folder, an actual drive)
    is gone, which denies traversal to a non-root user rather than reporting
    ENOENT the way a simply-missing folder would."""
    try:
        return path.is_dir()
    except PermissionError:
        return False


def autodetect_mount(expected_names=ALL_MODES) -> Path | None:
    """Scan common OS mount locations for the P-6.

    Prefers a volume actually named P-6, whatever it currently contains -
    that way a device mounted in the "wrong" mode is still found (and can
    be reported as such) rather than this just saying "not found".
    """
    candidates = candidate_mount_roots()

    for candidate in candidates:
        if _safe_is_dir(candidate) and candidate.name.upper() == "P-6":
            return candidate

    for candidate in candidates:
        if _safe_is_dir(candidate) and any(
            _safe_is_dir(candidate / name) for name in expected_names
        ):
            return candidate

    return None


@dataclass
class DeviceState:
    connected: bool
    mount: Path | None
    mode: str | None  # one of ALL_MODES, or None if connected but ambiguous
    # Linux only: a block device (e.g. /dev/sdc) seen by find_unmounted_device
    # while not connected - distinguishes "plugged in but not mounted" (a
    # mount keybinding has something to act on) from genuinely absent.
    unmounted_device: Path | None = None


def detect_device_state(explicit_mount: Path | None = None) -> DeviceState:
    """The device's current connection/mode state.

    explicit_mount overrides autodetection (mirrors p6-lab's --mount/
    P6_MOUNT precedent) - useful for an unusual mount location, or tests.
    """
    mount = explicit_mount if explicit_mount is not None else autodetect_mount()
    if mount is None or not mount.is_dir():
        return DeviceState(connected=False, mount=None, mode=None)

    present = [name for name in ALL_MODES if (mount / name).is_dir()]
    mode = present[0] if len(present) == 1 else None
    return DeviceState(connected=True, mount=mount, mode=mode)


# --- Auto-mount/unmount: not something p6-lab's CLI does (it just waits
# for you to mount the drive yourself), but a real gap observed on this
# machine - a plugged-in P-6 can be *known* to udisks2 but not actually
# mounted until something asks (a file browser opening it, normally).
# Linux-only: macOS/Windows generally auto-mount removable media without
# needing this at all, so the gap doesn't exist there to begin with.

VOLUME_LABEL = "P-6"


async def _run_command(*args: str, timeout: float = 15.0) -> str | None:
    """Run a command, returning its stdout on success or None on any
    failure (missing binary, non-zero exit, timeout) - callers treat all
    of those the same way: this particular avenue didn't work."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    if proc.returncode != 0:
        return None
    return stdout.decode()


def _walk_block_devices(devices: list[dict]):
    for device in devices:
        yield device
        yield from _walk_block_devices(device.get("children") or [])


async def _list_block_devices() -> list[dict]:
    if platform.system() != "Linux":
        return []
    output = await _run_command("lsblk", "-J", "-o", "NAME,LABEL,MOUNTPOINT")
    if output is None:
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    return list(_walk_block_devices(data.get("blockdevices", [])))


async def find_unmounted_device(label: str = VOLUME_LABEL) -> Path | None:
    """A block device (e.g. /dev/sdc) labelled `label` that's plugged in
    but not yet mounted. Linux only - returns None on any other platform."""
    for device in await _list_block_devices():
        if device.get("label") == label and not device.get("mountpoint"):
            return Path(f"/dev/{device['name']}")
    return None


async def find_device_for_mount(mount: Path) -> Path | None:
    """The reverse lookup - the block device currently mounted at `mount`,
    needed to unmount later since udisksctl unmounts by device node, not
    by path."""
    for device in await _list_block_devices():
        if device.get("mountpoint") == str(mount):
            return Path(f"/dev/{device['name']}")
    return None


async def mount_device(device: Path) -> Path | None:
    """Mount `device` via udisksctl, returning where it landed, or None
    on failure."""
    output = await _run_command("udisksctl", "mount", "-b", str(device))
    if output is None:
        return None
    match = re.search(r"Mounted .+ at (.+?)\.?\s*$", output.strip())
    return Path(match.group(1)) if match else None


async def unmount_device(device: Path) -> bool:
    """Unmount `device` via udisksctl. Returns whether it succeeded."""
    return await _run_command("udisksctl", "unmount", "-b", str(device)) is not None


async def ensure_mounted(label: str = VOLUME_LABEL) -> Path | None:
    """Find a present-but-unmounted P-6 and mount it. None if there isn't
    one, or mounting it failed."""
    device = await find_unmounted_device(label)
    if device is None:
        return None
    return await mount_device(device)


async def unmount(mount: Path) -> bool:
    """Unmount whatever's at `mount`. False if nothing's found there, or
    unmounting it failed."""
    device = await find_device_for_mount(mount)
    if device is None:
        return False
    return await unmount_device(device)


async def detect_or_mount() -> DeviceState:
    """Detection, but if nothing's found, also try auto-mounting a
    present-but-unmounted P-6 first (see ensure_mounted) before giving up.

    Meant to be called once, e.g. at app startup - not for repeated
    polling, since (unlike detect_device_state) it can perform a real
    mount action, not just read state.
    """
    state = detect_device_state()
    if state.connected:
        return state
    mounted_at = await ensure_mounted()
    if mounted_at is not None:
        return detect_device_state(explicit_mount=mounted_at)
    # Auto-mount didn't land anywhere (nothing to mount, or the mount
    # itself failed) - still worth telling the user a device is visible
    # so a manual "m" retry has something to act on, rather than just
    # reporting "not connected" the same as truly nothing plugged in.
    return await detect_device_state_async()


async def detect_device_state_async(label: str = VOLUME_LABEL) -> DeviceState:
    """detect_device_state, plus (Linux only) awareness of a P-6 that's
    plugged in but not yet mounted - read-only (no mount attempt), so
    it's safe to call on every poll tick, unlike detect_or_mount.
    """
    state = detect_device_state()
    if state.connected:
        return state
    unmounted_device = await find_unmounted_device(label)
    if unmounted_device is None:
        return state
    return DeviceState(connected=False, mount=None, mode=None, unmounted_device=unmounted_device)
