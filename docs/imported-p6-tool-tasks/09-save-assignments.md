# Brief

Copy the samples into the assigned pad locations

# Additional Info

- Option should warn if a device is not mounted
- the operation needs a confirmation before being actioned
- we could use 's' for send, when a configurtion is highlighted

# Implemented

This is `08-assignment-grid.md`'s **Not yet built** "Device transfer" module - actually copying assigned samples onto the device, which that task explicitly left undone (it only edited/saved assignments, never touched the device).

## `device.send_configuration()` (`src/p6_tool/device.py`)

Ported from p6-lab's `p6tool/send.py` (a sibling project's working CLI for this exact device, same lineage as the rest of `device.py`), not reimplemented from scratch:

- For each `(bank, pad) -> sample_path` assignment, sorted for a deterministic order: if the source file no longer exists, it's recorded in `SendResult.missing` and skipped entirely - the pad's existing contents (from an earlier send) are left untouched rather than cleared without a replacement.
- Otherwise, `mount/IMPORT/BANK_x/PAD_y/` is cleared of whatever files it already held, then the new sample is `shutil.copy2`'d in. Clearing only happens once a replacement source is confirmed to exist, matching p6-lab's own ordering (check source, *then* clear, *then* copy).
- Returns a `SendResult(sent, missing)` - `sent` is a plain count, `missing` is the list of assignments' original (string) `sample_path`s that didn't resolve to a real file, for the caller to report.

`IMPORT_MODE_INSTRUCTIONS` (also lifted verbatim from p6-lab's `send.py`) is the message shown when the device isn't in the right mode to receive a send.

## `s` on `ConfigList`, not `AssignmentGrid`

The brief's "when a configuration is highlighted" points at `ConfigList`, not the grid - `AssignmentGrid` already gave up `s` entirely for autosave (see `08-assignment-grid.md`'s last section), and this is a different action anyway: sending is about a whole configuration, not a single pad.

`ConfigList.action_send_to_device()`:

- No-ops if nothing's highlighted (`self.index is None`), same guard `d` already uses.
- Warns ("No assignments to send.") and stops if the highlighted configuration has none.
- Reads `device_state` off the app (`getattr(self.app, "device_state", None)` rather than a direct attribute access, since `ConfigList` is also mounted standalone in its own tests against a plain `App` with no such attribute at all) and warns instead of proceeding if it's missing, not connected, or not mounted ("P-6 not connected - connect and mount it before sending.") - covers the brief's "warn if a device is not mounted".
- Warns with `device.IMPORT_MODE_INSTRUCTIONS` if the device is connected but not currently in `MODE_IMPORT` (e.g. still mounted from a previous `EXPORT`/`BACKUP`/`RESTORE` session) - sending would otherwise write into a mount root with no `IMPORT` folder at all.
- Otherwise pushes `ConfirmSendModal`, and on confirmation calls `device.send_configuration()`, notifying either a plain success count or (if anything was missing) a combined "sent N; M missing and skipped" warning.

No `check_action` hiding of `s` when it wouldn't do anything - `08-assignment-grid.md` already tried and reverted that approach for this exact reason: `check_action` returning `False` blocks the action method (and its `notify()` calls) from ever running, which defeats surfacing *why* nothing happened.

## `ConfirmSendModal` (`src/p6_tool/widgets/config_list.py`)

Satisfies "needs a confirmation before being actioned" - same `OptionList` + detail-pane shape as `ConfirmDeleteModal` (position indicator in the border, second option always "cancel", `escape` also cancels), copied rather than factored into a shared base since the two differ in option count semantics, wording, and border colour, and the existing `_ChordPickerModal` precedent in `assignment_grid.py` shows this codebase already tolerates one shared shape implemented twice rather than forcing an abstraction across unrelated modals. Styled `$success` (matching `NewConfigurationModal`), not `$error` like `ConfirmDeleteModal` - sending doesn't destroy anything, so it doesn't belong under the same "irreversible, be careful" colour as delete.

# Tests

14 more tests, 157 total:

- `test_device.py`: `send_configuration()` in isolation - copies to the right `BANK_x/PAD_y` folder, skips a missing source and reports it without touching that pad, clears a stale file before copying a replacement, leaves a pad's existing file alone when its own source is missing, and no-ops on a configuration with no assignments.
- `test_config_list.py`: `s` with nothing highlighted, with no assignments, with the device not connected, and with the device connected but in the wrong mode - all notify and open no modal. `s` then confirm actually copies and notifies a plain count; cancel (`escape` or navigating to "Cancel") sends nothing; a mix of one real and one missing source sends the real one and notifies the combined count.
- `test_send_to_device.py` (new): one full chord end-to-end through `P6ToolApp` - create a configuration ("n"), assign a sample to it from the file browser ("a"/"e"/"4"), then send it ("s"/confirm) - checking the file actually lands on the fake mount.

Not confirmed against a real, physically connected P-6 - no device was plugged in while implementing this - only against the on-disk `IMPORT/BANK_x/PAD_y/` layout `device.py`'s own docstring already documents (and p6-lab's working CLI copies to identically).

# Not yet built

- Nothing prompts to unmount the device after a successful send, or to confirm on the device per `02-implementation-plan.md`'s original "confirm on the device" note - out of scope here since that's a physical action on the device itself, not something the app can drive.

# Bug reports: "out of space" during send, and the UI stalling while it copies

Two things reported after actually using this against a real P-6: a send failed with "out of space", and the UI froze for the duration of the copy.

## Root cause of "out of space": a real disk-full, not a per-sample length limit

Checked against the actual Roland manual (`docs/P-6_eng01_W.pdf`, now added to the repo) rather than guessing. Two separate constraints turned out to be involved, and the bug was the first one, not the second:

- **The mounted IMPORT volume's real free space.** It's an actual (if small) mass-storage volume, and `send_configuration()` just does plain file copies onto it - so it fails exactly the way any other too-big-for-the-disk copy would. This is what "out of space" actually was - confirmed with the user: it surfaced as an OS-level error from this tool's own `shutil.copy2` call while copying, not a message shown on the device itself after power-cycling.
- **Per-pad audio-time.** The manual's "Main specifications" page (p.151) publishes a maximum sample time that varies by rate/bit depth (e.g. 5.9s mono @ 44.1kHz, half that for stereo), but "Loading samples (Import)" (p.88-90) says plainly: "Data that exceeds the size of the sample pads is truncated." Silent, non-fatal, no error - so this was never going to be the cause of an "out of space" message, even though it's a real limit worth surfacing separately (see below).

**Correction from the user after the first pass of this fix:** IMPORT is a one-way staging area, not a live view of the device's sample memory - there's no way to see via USB what's actually loaded on a pad (EXPORT is the direction that does that, one bank at a time). Reworded `send_configuration()`, `check_available_space()`, and `ConfirmSendModal`'s confirm text accordingly - they'd said things like "replacing whatever's already in each pad", which reads as if the staging folder mirrors the device's current pad contents. It doesn't; whatever's sitting there is just leftover from an earlier send (ours or otherwise), never "the current sample on that pad". The actual clear-before-copy behaviour didn't need to change, only the wording describing it.

## `device.check_available_space()` - fixes the reported bug

Compares the total size of every assignment whose source still exists against `shutil.disk_usage(mount).free` - a live read of the actual mount, not a guessed capacity figure. Credits back whatever's already sitting in each target pad folder, since `send_configuration()` clears a pad before copying its replacement in - that space is freed before the new file needs it, so charging for both would overstate what's needed.

`ConfigList.action_send_to_device()` runs this check right after the connectivity/mode guards, before ever pushing `ConfirmSendModal` - a `SpaceCheck.fits is False` warns with both numbers (`device.human_bytes()`, ported from p6-lab's `fsutil.human_size`) and stops, the same way the connectivity/mode guards already do, rather than letting the user hit the same copy failure again.

## `device.truncation_risks()` - a best-effort answer to "is it the whole configuration, or a specific sample"

Answers that question directly: it's per-sample, and it's about audio *time*, not the size of the configuration as a whole (48 pads max is already enforced by the grid itself). The manual only publishes four mono-at-a-specific-rate figures rather than a per-pad byte budget, but each one multiplies out to the same ~520KB at 16-bit (e.g. 5.9 × 44100 × 2 ≈ 520380) - `PAD_MEMORY_BUDGET_BYTES` treats that as a fixed per-pad budget, which generalises to any imported file's own sample rate/channel count via `budget / (frame_rate × channels × 2)` rather than only the four rates the device itself records at.

Explicitly a **best-effort approximation, not a device-verified constant** - the manual says available import time "varies with sample rate and bit rate" but publishes no figures for anything other than the implied-16-bit rows above, so this assumes the device stores everything internally at 16-bit regardless of an imported file's own bit depth. Reuses `waveform.get_format_info()`/`get_duration_seconds()` (already built for the preview pane's waveform rendering) rather than re-parsing WAV headers.

Wired into `ConfirmSendModal`'s own confirm-option detail text (not a separate warning dialog) - a sample flagged this way still sends fine per the manual (it just comes back truncated later), so it belongs alongside the "here's what will happen" confirmation, not as a second gate the disk-space check.

## The UI stalling - `send_configuration()` moved to a worker

The original `action_send_to_device` called `device.send_configuration()` directly from the confirm-modal's dismiss callback, on the main thread - blocking the whole UI event loop for however long the copy took, exactly as reported. Fixed the same way `DevicePanel`'s mount/unmount already handle a slow operation: `self.run_worker(self._send(...), exclusive=True, group="send", name="send")`, with `_send()` wrapping the blocking call in `asyncio.to_thread()` rather than making `send_configuration()` itself async (it's plain synchronous file I/O, no natural async boundary to await on, unlike the subprocess-based mount/unmount). An immediate "Sending to the device..." notification fires before the worker starts, since a multi-file copy over USB can take a noticeable moment and silence would read as nothing happening.

**Test-only gotcha found while writing this:** `app.workers.wait_for_complete()` with no arguments waits for *every* worker in the whole app, not just the one just started - in the full `P6ToolApp`, `FileBrowser`'s own unrelated background directory-loader worker can get cancelled during ordinary UI activity (focus changes etc.) at any point, which fails that bare wait via `asyncio.gather` even though the send itself completed correctly. Tests scope it to `[w for w in app.workers if w.group == "send"]` instead of the bare call.

# Bug report: still "not enough space" even for a small configuration - the tree was already full

Reported after the fix above: `check_available_space` was now correctly *reporting* the problem ("needs ~9.7MB, ~3.0KB free") rather than crashing mid-copy - but nothing could be sent at all, on a device with plenty of nominal capacity for a handful of samples.

Diagnosed directly against the user's actually-connected P-6 (`device.detect_device_state()` found it mounted at `/run/media/stuart/P-6`) rather than guessing:

```
$ df -h /run/media/stuart/P-6
Filesystem      Size  Used Avail Use% Mounted on
/dev/sdc         10M   10M  3.0K 100% /run/media/stuart/P-6
```

IMPORT is a fixed **~10MB** partition, and it was already 100% full - 47 of the 48 pad folders held `.wav` files dated **2015**, clearly the device's factory-default demo kit (Kick-Dirt, Perc-Tone, FX-Matrix, Morphbot, Misc, ...), still sitting there staged. The 48th held a leftover from an earlier real test of this feature. None of it had ever been cleared, because every send up to this point - correctly, per the manual, but incompletely - only ever cleared the *specific* pads it was about to (re)write. Everything else just accumulated, permanently consuming the entire tiny budget.

Since IMPORT is one-way staging (not live device state - see the correction above), none of that leftover data represents anything worth preserving. Fixed by having `send_configuration()` wipe the *entire* `IMPORT` tree (`shutil.rmtree`) before writing anything, not just the pads this configuration assigns - a full "here's everything I want imported now" batch, matching the manual's own one-shot stage-then-`[KYBD]` workflow rather than an incremental one. `check_available_space()` now credits back the entire existing tree's size the same way, not just the touched pads' - on the user's real device this alone should turn "~3.0KB free" into "~10MB free" for the very next send.

`ConfirmSendModal`'s confirm-option text now says so explicitly ("clearing anything currently staged there first (including any other configuration's samples not yet imported)") rather than implying only this configuration's own pads are touched - still styled `$success` rather than `$error` (nothing on the device's *actual* memory is destroyed, only pending staged data), but the user should still know the whole tree gets cleared, not just what they're sending.

# Tests

11 more tests, 168 total:

- `test_device.py`: `human_bytes()` formatting; `check_available_space()` fitting, not fitting, crediting back the *entire* existing IMPORT tree (a stale file in a touched pad and one in an untouched pad, both credited), and ignoring missing sources; `send_configuration()` wiping an untouched pad's leftover file (not just the ones it writes) and producing no file at all for a pad whose source is missing (updated from the old "leaves it untouched" expectation, now that nothing staged is worth protecting); `truncation_risks()` flagging a sample that's too long for its rate/channels, saying nothing about one that fits, and skipping a missing source.
- `test_config_list.py`: `s` refuses and notifies (no modal) when there isn't enough free space; the confirm modal's detail text warns about a sample likely to be truncated, naming it.
- Existing `s`-then-confirm/cancel tests updated: the mount directory now has to exist first (`check_available_space` needs somewhere real to statfs), and confirm-path tests wait for the "send" worker group specifically rather than a bare `wait_for_complete()`, per the gotcha above.

This time confirmed against the user's real, physically connected P-6 (diagnosis above), not just synthetic `tmp_path` mounts - though the actual fixed send still wasn't re-run against it live as part of this change; that's still the user's to try next.

# Follow-up: the warning compared numbers on two different bases

Reported again after the whole-tree-wipe fix landed: the user was still seeing a "not enough space" warning and asked for confirmation that pads are cleared before a send starts (they already were, per the fix above) - the real problem turned out to be in what the warning *displayed*, not in whether the send itself would actually work.

`check_available_space`'s `needed_bytes` was netted against the existing tree (a small or even negative number once credited), but `free_bytes` was still the *raw, pre-wipe* `shutil.disk_usage(mount).free` (e.g. the ~3.0KB from the device's near-full state) - two numbers from different moments in time, shown side by side as if directly comparable. A configuration close to the device's real ~10MB ceiling would show something like "needs ~9.7MB, ~3.0KB free", which reads exactly like the original bug even when the fix underneath was already correctly accounting for the wipe - there was no way to tell "just needs clearing" apart from "genuinely too big for this device" from the message alone.

Fixed by putting both numbers on the same (post-wipe) basis instead: `needed_bytes` is now the plain, un-netted total of every assignment; `free_bytes` is `shutil.disk_usage(mount).free` *plus* whatever the existing IMPORT tree would give back by being wiped - i.e. what's actually available right before `send_configuration` starts copying. `ConfigList.action_send_to_device`'s warning text was reworded to say "available ... even once its IMPORT folder is cleared", so a refusal at this point now unambiguously means the configuration exceeds the device's real capacity, not that stale content is in the way.

Re-verified directly against the user's real, connected P-6 (still holding the full factory-demo tree at the time): a synthetic ~9.6MB configuration now correctly reports `fits=True` with `free_bytes` ≈ 9.9MB (`shutil.disk_usage(mount).free` + the ~10MB reclaimable tree) - the same shape of configuration that previously reported "needs ~9.7MB, ~3.0KB free" now reads as available.

1 more test, 169 total (plus an existing one's assertions updated for the new, non-netted `needed_bytes`): `check_available_space` genuinely not fitting even after crediting the whole reclaimable tree back, alongside the already-updated fitting case.

# Feature: each configuration's total size, coloured if it won't fit

Requested once the space checks above existed: rather than only finding out at send time, show each configuration's total size directly in `ConfigList`, coloured if it's already known to be too big for the connected device.

- `device.configuration_size_bytes()` and `device.available_bytes_once_cleared()` pulled out of `check_available_space()` as their own functions (it's now a two-line wrapper around them) - the same "total assigned size" and "what would actually be available" numbers are exactly what the list needs per row/once-per-refresh, not just what the send guard needs.
- `ConfigList._config_label()` builds each row's label as a Rich `Text`: the name, plus `"  " + human_bytes(size)` appended in `dim` if the configuration comfortably fits (or there's nothing connected to judge it against) or `bold red` if it's known not to. A configuration with no assignments shows no size at all - nothing to warn about.
- `refresh_list()` computes `available_bytes_once_cleared(mount)` once per refresh (not once per row - it doesn't depend on which configuration is being sized) from `getattr(self.app, "device_state", None)`, same pattern `action_send_to_device` already uses for the same reason (`ConfigList` is also mounted standalone in its own tests, with no such attribute at all). Wrapped in `try`/`except OSError` - a `DeviceState` claiming connected+mounted doesn't guarantee `shutil.disk_usage` will actually succeed at this exact instant (unplugged mid-render, or in tests, a hand-built `DeviceState` pointing at a mount that was never created) - falls back to `None` (no verdict) rather than crashing the list.
- `P6ToolApp.on_mount`/`_poll_device` both now also call `configs.refresh_list()` after resolving/changing `device_state` - `ConfigList`'s own `on_mount` already ran (and rendered) before that state was known, and a later connect/disconnect/mode change can flip whether a configuration fits, so the colouring needs to follow live, not just from whatever was true at the list's own first render.

**Found and fixed while wiring this up:** `refresh_list()`'s `clear()` + re-`append()` was silently dropping the ListView's highlight to `None` on any call after the very first one - Textual's `ListView` only applies its own `initial_index` (defaulting the highlight to row 0) the one time it mounts with children; a later manual rebuild doesn't get that for free. Harmless before now (nothing else called `refresh_list()` after initial mount except in response to a user action that was about to change the highlight anyway, e.g. "n"/"d"), but the new device-triggered refresh calls happen at arbitrary, unrelated moments - losing the user's current highlight out from under them the next time the device's poll tick fires would have been a real regression. Fixed generally (not special-cased to this feature) by having `refresh_list()` save `self.index` before clearing and restore it afterward, same "position survives a rebuild" shape as `AssignmentGrid._layout_grid()` already uses for its own cursor.

6 more tests, 179 total: `_config_label()` in isolation (no size shown for an empty configuration, `dim` with no verdict available, `bold red` vs `dim` for the same configuration against two different `available` figures) - called directly against a bare `ConfigList()` instance rather than through a mounted app, since it doesn't touch `self.app` at all; a size actually appears in a real rendered list; `refresh_list()` is wired to call it with `device.available_bytes_once_cleared()`'s real result (spied rather than inspected via rendered style, since Textual's Content/Visual rendering pipeline doesn't hand the original `Text`'s style spans back out through a mounted widget); highlight survives an explicit `refresh_list()` call after navigating away from row 0.

Re-verified directly against the user's real, connected P-6 again: `configuration_size_bytes`/`available_bytes_once_cleared` compute sensible, consistent numbers against its actual (still factory-demo-full, at time of writing) IMPORT tree.

# Bug: the "found and fixed" highlight fix above didn't actually work

Reported: "the selected configuration is no longer highlighting." The save/restore added just above was real but incomplete - it restored `self.index`'s *value* correctly, but not the resulting visual highlight, and nothing in the test suite checked that distinction.

Root cause, confirmed directly (a small standalone repro script against the real widget, not just re-reading the code): `ListView.append()` schedules a mount rather than completing it synchronously - the newly-created `ListItem` nodes aren't actually attached yet at the point `refresh_list()` returns. Setting `self.index = previous_index` immediately after the `append()` loop fires `ListView`'s own `watch_index`, but that watcher's `_is_valid_index(new_index)` check runs against `self._nodes` *before* the pending mounts have landed, so its "set `new_child.highlighted = True`" side effect silently no-ops. The reactive `index` value itself still ends up correct (which is exactly why `configs.highlighted_configuration`/`configs.index` - what every existing test checked - looked fine) - only the visual flag on the actual node was ever missing, and once `watch_index` has run once for a given value, it doesn't get a second chance to re-apply that side effect just because the nodes show up moments later.

Fixed by deferring the restore with `self.call_after_refresh(setattr, self, "index", previous_index)` instead of assigning inline - runs after the pending mount has actually settled, by which point `watch_index` finds real nodes to flag. Confirmed by reverting to the inline assignment and re-running the new regression test below - it fails against the old code and passes against the fix, not just "passes now" on faith.

**Gap this exposed**: every existing highlight-related test (including the "6 more tests" added just above) checked `index`/`highlighted_configuration` - the semantic position - never the `ListItem.highlighted` reactive that actually drives the visible highlight. Both had always moved together before, since nothing had ever set `index` inline against not-yet-mounted nodes until this feature did.

1 more test, 182 total: `test_list_visually_highlights_the_restored_row_not_just_its_index` reads `configs._nodes[configs.index].highlighted` directly (and confirms every *other* node's flag is `False`), not just `highlighted_configuration` - specifically so a future change to this same restore logic can't reintroduce the same "value's right, node's not flagged" gap unnoticed. The existing `test_list_preserves_highlight_across_a_device_triggered_refresh` needed a second `pilot.pause()` added - `call_after_refresh` runs on the *next* refresh cycle after the one that scheduled it, not the same one.

# Bug: the actual import never worked - unflushed writes lost on power-cycle

Reported: "the import process doesn't appear to be working, even though the files are in place" - `[KYBD]`'s own "donE" appeared almost instantly (the manual says a real import "may take some time"), the pads never actually changed sound, and remounting afterward showed some pad folders created but *empty*, one populated, and others missing entirely - all created within the same minute.

First confirmed the direct question this started from: yes, `send_configuration()` does recreate the whole `BANK_x/PAD_y` folder structure from scratch every time (it `shutil.rmtree`s the entire `IMPORT` tree up front, then `mkdir(parents=True)`s exactly the pads the configuration assigns - see the section above). A pad with no assignment simply gets no folder at all, which is normal (the factory kit itself had gaps the same way - `BANK_A` never had a `PAD_6` either) and not what was actually wrong.

The real cause: `shutil.copy2` only guarantees a file's bytes reach the OS's page cache, not the physical medium - an ordinary desktop workflow relies on a *clean unmount* (which blocks until the kernel has actually written everything back) to close that gap before the media is removed. Per the manual's own import steps, step 5 ("eject the drive") happens *before* step 6 ("press [KYBD]") for exactly this reason. Nothing in `action_send_to_device`/`_send` ever did that - the drive was left mounted after a send, so cleanly ejecting it was a manual step the user had to remember and separately perform before power-cycling the device, and it was getting skipped. Linux's write-back cache gives no ordering/completeness guarantee across multiple files if the underlying block device disappears before a sync - some writes (apparently smaller/earlier ones) can land while others are still purely in cache and vanish outright when power is cut, which explains the mixed populated/empty/missing pads exactly: not a bug in *which* folders got created, but in *which of their contents* actually made it to the physical device before it was power-cycled.

Fixed on both ends:

- `device.send_configuration()` now explicitly `fsync`s every copied file *and* the directory chain up to `mount` (`_fsync_path`/`_fsync_up_to`, new) as it goes - a file's own content fsync alone doesn't make its *directory entry* durable, so both need it. Also fsyncs `mount` once at the end unconditionally, covering the case where the loop never runs at all (nothing assigned, or every source missing) but the `IMPORT` tree still just got wiped. Skipped on Windows (no `os.O_DIRECTORY` to open a directory with there) - same per-platform-quirk reasoning as `candidate_mount_roots`.
- `ConfigList._send()` now calls `device.unmount(mount)` (the same helper `DevicePanel`'s own `u` binding already uses) right after the copy finishes, rather than leaving the drive mounted and hoping the user ejects it themselves before power-cycling. The final notification reflects the outcome either way: "Safely ejected - you can power-cycle the device now" (and `self.app.device_state`/the list's own size colouring get refreshed to reflect it's gone) or, if unmounting itself failed, "Couldn't safely eject automatically - eject it yourself before power-cycling, or the import may not see everything" - `severity="warning"` in that case, same as a missing-source send already got.

2 more tests, 183 total: the confirm-then-send tests updated for the new message text (in this test suite's mocked-subprocess environment, `device.unmount()` can never find a matching real block device, so the "couldn't eject automatically" branch is what they now correctly expect - not a regression, just what actually happens with no real hardware present); a new test monkeypatches `device.unmount` to succeed and confirms the "safely ejected" message, `app.device_state` updating to disconnected, and the list refreshing.

Not yet re-verified against the user's real P-6 with this specific fix - the diagnosis (unflushed writes, no clean eject before power-cycle) was reasoned from the symptoms and the manual's own documented step ordering, not confirmed by reproducing the exact failure directly. Next real-hardware attempt is the actual test.

# Follow-up: still not working - stopped recreating directories, only clear files now

Reported again: the fsync/eject fix above didn't fix it either. The user's own hypothesis: `send_configuration` was `shutil.rmtree`-ing the whole `IMPORT` tree and recreating every `BANK_x/PAD_y` folder from scratch on every send - on a real FAT-formatted device volume, a plain host-side `mkdir` recreating a folder the factory originally created might not reproduce whatever attributes/permissions the device's own firmware expects there, which could make it silently ignore folders it doesn't recognise as "really" the import destination.

Not independently confirmed (no way to inspect the P-6's own FAT attribute expectations from here), but it's a plausible mechanism, directly implicated by what changed between "worked at some point" and "stopped working", and - importantly - cheap and safe to just not do, so fixed on the strength of the theory rather than holding out for proof:

- `send_configuration()` no longer touches directories at all. Instead of `shutil.rmtree(import_root)` up front, it walks the existing tree and unlinks every *file* it finds, leaving every folder - factory-original or otherwise - exactly as it was. `pad_dir.mkdir(parents=True, exist_ok=True)` is now only ever a no-op for a folder that already exists; it only actually creates one that's genuinely missing (e.g. a pad nothing has ever been sent to before).
- This still fully addresses the original "not enough space" bug the whole-tree wipe was for - the tiny IMPORT partition's space is consumed by file *content*, not by empty directory entries, so clearing files everywhere (not just the pads this send touches) frees essentially all of it either way.
- `available_bytes_once_cleared()`'s accounting is unchanged (it already only ever summed file sizes, never counted directories as reclaimable space) - only `send_configuration`'s own docstring and comments needed rewording to stop describing this as a "wipe"/"tree" operation.

3 more tests, 184 total: the two tests that asserted an untouched pad's *folder* was removed now assert the opposite - the folder survives, only the stale file inside it is gone (`test_send_configuration_clears_files_in_untouched_pads_too`, renamed from `..._clears_the_entire_import_tree_not_just_touched_pads`; the missing-source test similarly renamed/reasserted). A new test, `test_send_configuration_never_deletes_or_recreates_existing_pad_folders`, checks this directly via inode identity (`stat().st_ino` unchanged before/after) rather than a weaker "a file ends up in there somehow" check that a delete-and-recreate would still pass.

Still unverified against the real device - same as the fsync/eject fix above, this is reasoned from a plausible, testable mechanism and the user's own direct observation of what changed, not a reproduce-then-fix loop against actual hardware. If this *still* doesn't resolve it, the next thing worth checking directly against the device is whether the copied WAV files' own encoding (sample rate/bit depth/channels) matches something the importer actually accepts, rather than anything about the file-copy mechanics themselves.
