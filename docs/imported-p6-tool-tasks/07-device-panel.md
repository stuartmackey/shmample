# Brief

A panel that shows if a device has been connected and what state it is in

- import samples
- import patterns
- export samples (and which bank is active)
- export patterns

The structure of the drive will decide what mode it is in.

# Reference: `p6-lab`'s existing `p6backup`/`p6config` tools

A sibling project (`p6-lab`) already has a working CLI (`p6backup`) and TUI (`p6config`) for this exact device, pasted in full as background and distilled here to what's actually relevant to this panel. Confirms/answers most of what the earlier review below flagged as blocked - only a couple of genuine gaps remain (marked at the end).

## The four modes

The P-6 mounts as a USB drive in exactly one of four modes at a time, chosen by a button combo held at power-on - **the mode is fixed by which folder name is present at the mount root**, not something inferred from contents:

| Folder at mount root | Mode |
|---|---|
| `IMPORT` | sample import (already known from `01-initial-description.md`: `IMPORT/BANK_A..H/PAD_1..6/`) |
| `EXPORT` | sample export |
| `BACKUP` | pattern backup (export) |
| `RESTORE` | pattern restore (import) |

So "detect what mode it's in" is just: check which one of these four folder names exists at the mount root. No signature ambiguity to design around.

## Sample export

- `EXPORT/BANK_X/PAD_Y/` contains **both** `*.WAV` and `*.PRM` per populated pad - a `.PRM` (device parameters: pitch/level/etc, opaque binary) alongside the sample, unlike import (see below).
- **Exporting is one bank at a time, and this is a hardware limitation, not a folder-listing quirk** - the device only exposes whichever single bank the user selected on the device itself before mounting. There's no file/folder signature for "which bank is active"; the panel can only see whatever `BANK_X` folder(s) happen to be present in the current `EXPORT` mount, and a full multi-bank export means repeating "select bank on device → power-cycle → mount" per bank.

## Sample import

Confirms what's already built/assumed: drop a `.WAV` into `IMPORT/BANK_X/PAD_Y/`, no `.PRM` needed - "the device takes care of the rest." `p6backup send` (pushing a saved config onto the device) clears out anything already in a pad's folder before copying the new sample in.

## Patterns

- Files named `P6_PTN1-01.PRM` ... `P6_PTN4-16.PRM` - 4 groups x 16 patterns, `.PRM` (same opaque binary format as the per-pad device-parameter files above). Treated as an opaque blob to copy whole, never parsed.
- **Gap resolved** - checked `p6-lab`'s actual `backup.py`: it copies straight from `mount/BACKUP` (`fsutil.copy_tree(source, dest)` where `source` is the `BACKUP` folder itself). The `patterns/` subfolder only exists in `p6backup`'s own local archive destination - on the device, the `.PRM` files sit directly under `BACKUP`/`RESTORE`, no nesting.

## Mount discovery

`p6backup` doesn't assume a single fixed path (the brief's `/mnt/run/$USERNAME/p-6` guess doesn't match this) - it scans the common candidate locations for whichever mode-folder is currently expected:

- macOS: `/Volumes/*`
- Linux: `/run/media/$USER/*`, `/media/$USER/*`, `/mnt/*`
- Windows: drive letters

Falls back to asking the user to type a path if nothing's found, plus a `P6_MOUNT` env var / `--mount` flag to skip detection entirely. This resolves the open "how do we find the mount" question from `02-implementation-plan.md` - worth adopting the same multi-location-scan-plus-override approach rather than a single assumed path.

## Overlap with existing p6-tool design

- `p6config` (the existing tool) is essentially a predecessor of this very project: two-pane screen, sample-library tree + bank/pad assignment grid, `a` assign / `c` clear / `s` save, JSON configs on disk. Validates the direction already taken here, nothing new to change.
- `p6backup send` - copy a saved config's samples onto `IMPORT/BANK_X/PAD_Y`, clearing each target pad first, `.WAV` only - is the concrete precedent for `02-implementation-plan.md`'s **Device transfer** module.

## Open questions for you

1. Real `ls -R` of a device mounted in `EXPORT` mode, to confirm the `.WAV`+`.PRM` per-pad structure directly rather than from memory of the other tool.

## Decided: reimplement natively, don't depend on `p6-lab`

`p6-lab`'s code was read as reference (`config.py`, `device.py`, `send.py`) but not imported - p6-tool stays self-contained as its own library, no dependency on that sibling project.

## Implemented

`src/p6_tool/device.py` - ported (not imported) the mount-detection logic:

- `candidate_mount_roots()` - same platform-aware scan as `p6-lab`'s version (`/Volumes` on macOS, `/run/media` + `/media` + `/mnt` on Linux scanned two levels deep since `$USER` isn't always available from the environment, drive letters on Windows).
- `autodetect_mount()` - prefers a volume literally named `P-6` regardless of contents (so a device mounted in an unexpected mode is still found and can be reported as such, not just "not found"), else the first candidate containing one of the four mode folders.
- `detect_device_state(explicit_mount=None) -> DeviceState` - the actual "is it connected, and what mode" query this panel needs; `connected`/`mount`/`mode` (`None` when connected but ambiguous - no mode folder present, or more than one, which shouldn't happen given the device only exposes one at a time but isn't assumed). `explicit_mount` mirrors `p6-lab`'s `--mount`/`P6_MOUNT` override precedent.

**Deliberately not ported**: `p6-lab`'s CLI prompt loop (`wait_for_one_of`'s blocking `input()`/`print()`) - a TUI polls/displays state rather than blocking on it waiting for a power-cycle.

9 new tests (`test_device.py`), 70 total, all passing - covering each of the four modes individually, the ambiguous cases (no mode folder, more than one), not-connected, and the platform-specific candidate paths.

Not yet built: the actual panel widget (this only covers the detection logic it'll be backed by), and the copy/transfer logic for each mode (that's `02-implementation-plan.md`'s **Device transfer** module, still a separate future task).

## Confirmed against a real, physically-mounted device

Not just synthetic tests - a real P-6 was mounted in `IMPORT` mode and checked directly:

- `ls -R` of `/run/media/stuart/P-6` matched the documented structure exactly: `IMPORT/BANK_A..H/PAD_1..6/` (all empty), plus `info.txt` at the root.
- It wasn't mounted automatically by anything (a file browser or otherwise) - `gio mount -l` showed the volume as *known* to udisks2 but not yet mounted, nothing had triggered an automount. Mounted manually for this check via `udisksctl mount -b /dev/sdc` (found via `udisksctl status`, labelled "P-6").
- `autodetect_mount()` correctly found `/run/media/stuart/P-6` (via the two-levels-deep scan under `/run/media`, exactly the case that scan depth exists for), and `detect_device_state()` correctly reported `connected=True, mode='IMPORT'` against the real mount.

## Auto-mount/unmount

Prompted by that "it wasn't mounted by anything" observation above - not something `p6-lab`'s CLI does (it only ever waits for you to mount the drive yourself), but a real gap worth closing: on this machine, the P-6 was *known* to udisks2 but stayed unmounted until something actually asked. Added to `device.py`, Linux-only (`lsblk -J`/`udisksctl`, both part of udisks2 - macOS/Windows generally auto-mount removable media without needing this at all, so there's no equivalent gap there to close):

- `find_unmounted_device()`/`find_device_for_mount()` - `lsblk -J` gives clean machine-parsable JSON (name/label/mountpoint, walked recursively for partitions nested under a parent device) rather than needing to scrape `lsblk`'s plain-text table output.
- `mount_device()`/`unmount_device()` - shell out to `udisksctl mount -b`/`unmount -b`, parsing `"Mounted X at Y"` for the resulting path.
- `ensure_mounted()` composes the two for the mount direction; `unmount()` for the reverse.
- `detect_or_mount()` - passive detection first, only attempts an auto-mount if nothing was found; wired into `P6ToolApp.on_mount()` so **the tool auto-mounts a present-but-unmounted P-6 on startup**, per your ask. Deliberately not folded into `detect_device_state()` itself, which stays a pure read-only query - suitable for repeated polling (e.g. a live status pane later) without it trying to mount something on every poll tick.

14 more tests (`test_device_mount.py`), 84 total. Confirmed against the real device again: unmounted it (`udisksctl unmount -b /dev/sdc`), ran `detect_or_mount()` for real (no mocks) - it found the unmounted device via `lsblk`, mounted it via `udisksctl`, and correctly reported `connected=True, mode='IMPORT'`. Then confirmed `unmount()` for real too, and remounted it back via `udisksctl` to leave the device ready for further testing.

Not yet built: the option to unmount *from within the running TUI* (a keybinding on the panel) - `unmount()` exists and is tested/confirmed working, just not wired to a key yet.

## Panel implemented - narrow, lazygit "Status"-pane style

`src/p6_tool/widgets/device_panel.py` - `DevicePanel(Static)`, fixed `height: 3` (not a share of the column like the other three panes) - modelled directly on lazygit's own tiny Status pane (one line: repo + branch) rather than a full pane's worth of content. Shows one of four states: checking, not connected, `"P-6 connected -> {mode}"`, or connected-but-unrecognised.

Added to `MainColumn` as the new top pane, everything else renumbered down: `[1] Device` / `[2] Configurations` / `[3] Samples` / `[4] Preview`, and the app-level numbered pane-jump bindings shifted to match. `can_focus = True` for the same reason as `PreviewInfo` - no bindings of its own, just needs to be a valid target for `1`.

`P6ToolApp.on_mount()` now pushes the result of `detect_or_mount()` into the panel directly (`self.query_one("#device", DevicePanel).show(state)`) rather than leaving the state unsurfaced - the "logic exists, not displayed yet" gap from the previous section is closed.

5 more tests (`test_device_panel.py`), 89 total, including one that mocks `device.detect_or_mount` to confirm the app actually wires its result into the panel, not just that the panel can render arbitrary states. Confirmed visually against the real mounted device too - `[1] Device` correctly showed `P-6 connected -> IMPORT` on startup.

## Unmount keybinding, live disconnect detection, and a lazygit-style context-sensitive footer

Closed the "not yet wired to a key" gap flagged above, plus two related requests: no way to tell when the device was removed/unmounted outside the app, and a lazygit-style footer listing keybindings for whatever pane is focused.

- `DevicePanel` gained `u` (Unmount) - stores the last `DeviceState` it was shown, and on `u` runs `device.unmount(mount)` as a worker (same `run_worker` pattern `FileBrowser` already uses for preview playback), then re-`detect_device_state()`s and pushes the fresh state into both itself and `app.device_state` rather than assuming success.
- `P6ToolApp` now polls `device.detect_device_state()` every 2 seconds (`set_interval`, `DEVICE_POLL_INTERVAL`) and pushes the result into the panel whenever it differs from the last known state - this is what makes an external unmount or unplug (or a drive that appears without the app having mounted it) show up without needing to press anything. Deliberately calls the read-only `detect_device_state()`, not `detect_or_mount()` - a poll tick shouldn't go mounting things, exactly the reasoning already written down in the auto-mount section above for why the two were kept separate.
- Added a Textual `Footer()` to the app's `compose()`. This turned out to need no bespoke context-sensitive logic at all - Textual's built-in `Footer` already reads `screen.active_bindings` (the focused widget's own `BINDINGS`, walked up through its ancestors) and re-renders whenever focus changes, which is exactly lazygit's per-pane keybinding list. Confirmed via screenshot: focused on `[1] Device` the footer shows `u Unmount`; focused on `[2] Configurations` it shows `n New` / `d Delete` instead, `u` gone.
- Adding the Footer took one row off the bottom of the screen, so the two layout tests asserting exact pane heights against a 40-row terminal (`test_column_takes_a_third_of_the_width_and_full_height`, `test_panes_split_the_column_height_one_three_one`) needed updating to 39 available rows.
- 6 more tests (`test_device_panel.py`), 94 total: the unmount action itself (and its no-op when disconnected), the app poll picking up a disappearance (and staying quiet when nothing changed), and the footer's binding list actually changing with focus.

Not yet built: item-level footer sensitivity (e.g. a different hint depending on which file/config is highlighted within a pane, not just which pane has focus) - lazygit does some of that, but every binding here is pane-level already, so there was nothing to differentiate.

## Mount keybinding for a visible-but-unmounted device

Closes the gap the other direction: `u` handled a mounted device going away, but a P-6 plugged in *after* the app started (or left unmounted because an auto-mount attempt failed) had no way to be picked up short of restarting the app.

- `DeviceState` gained `unmounted_device: Path | None = None` - the block device (Linux only, e.g. `/dev/sdc`) seen by `find_unmounted_device` while not connected, distinguishing "visible but unmounted" from genuinely absent.
- New `device.detect_device_state_async()` - `detect_device_state()` plus, only when not connected, a `find_unmounted_device()` check to populate `unmounted_device`. Read-only (no mount attempt), so it's what both the poll loop and the panel's post-action refresh use now, in place of the old sync `detect_device_state()`.
- `detect_or_mount()`'s fallback path (auto-mount found nothing, or the mount itself failed) now returns `detect_device_state_async()`'s result instead of a bare "not connected" - so even a failed auto-mount at startup still surfaces a retry option instead of silence.
- `DevicePanel` gained `m` (Mount), mirroring `u`'s `run_worker` pattern: calls `device.mount_device(unmounted_device)`, then re-detects and pushes the fresh state into both itself and `app.device_state`.
- `DevicePanel.check_action()` now hides whichever of `u`/`m` doesn't apply to the current state (returns `False` to hide, not just grey out) and calls `self.refresh_bindings()` at the end of `show()` so the footer re-asks it - the footer now shows *at most one* of Mount/Unmount, never both, never a dead key.
- 13 more tests (`test_device_panel.py`, `test_device_mount.py`), 102 total: the mount action itself (and its no-op when nothing's visible), the visible-but-unmounted display text, `check_action` covering all three states (mounted / visible-unmounted / absent), and the new `device.py` functions' lsblk-call behaviour.
