## Running Python/tests
Use `.venv/bin/python` directly (e.g. `.venv/bin/python -m pytest ...`). Don't `source .venv/bin/activate`.

## New panes/screens

Any new bordered pane or pushed `Screen` with its own keybindings must:
- Include a `Footer()` so its shortcuts are discoverable, unless every available action is
  already self-evident from what's on screen (e.g. a two-option confirm dialog like
  `ConfigList`'s `ConfirmDeleteModal`).
- Follow the existing numbered pane-jump convention: a `border_title` of `"[N] Name"` and a
  matching `Binding("N", "focus_pane('#id')", ..., show=False)` (see `ShmampleApp.BINDINGS`/
  `action_focus_pane` in `app.py` for the pattern across the main layout; a pushed `Screen`
  needs its own `action_focus_pane` method too, since actions don't inherit across screens).
- Not rely on vim-style `j`/`k` navigation alone for moving between panes - that only helps
  within a single list/tree, not for jumping between panes.

## Project overview

A Textual TUI for browsing/tagging/previewing drum samples and staging them into named "packs"
for a Roland P-6 (Novation Circuit Tracks support is a stated stretch goal, not yet started - see
`agents.md`). README.md has setup/testing/manual-smoke-test commands; `docs/tasks/` and
`docs/imported-p6-tool-tasks/` hold the feature briefs and decisions behind each area, worth
checking before assuming a design choice is arbitrary.

### Panes (numbered - see `ShmampleApp`/`MainColumn`'s `compose`)

1. Device (`device_panel.py`) - P-6 connected/mounted status, `u`/`m` to unmount/mount. Parked
   (`display = False`) pending the device-configuration screen described in
   `docs/tasks/03-handling-multiple-devices.md`.
2. Packs (`config_list.py`'s `ConfigList`) - saved packs, one JSON file per pack under
   `~/.config/shmample/configurations/`. `n` new (empty), `ctrl+a` new from a folder (recursive
   `.wav` import), `c` clone, `d` delete, `s` send to device, `e` export to a folder.
3. Samples (`file_browser.py`'s `FileBrowser`) - the sample tree across configured samples
   directories. `space` multi-select, `a` add (selection or cursor) to Holding, `t` auto-tag,
   `Shift+R` rescan, `Shift+A` add another samples directory (via `DirectoryPickerModal`).
4. Tags (`tag_browser.py`'s `TagBrowser`) - tag list with counts; `space` toggles a tag as an
   AND filter on the Samples pane, scoped to whichever Samples-pane folder is currently focused.
5. Holding (`holding_area.py`'s `HoldingArea`) - device-agnostic staging list for the pack
   currently open, backed by `configuration.pack.holding` (just an ordered list of paths, deduped
   on add). `a` assigns the highlighted sample to a device pad.
6. Preview (`preview_info.py`) - duration/format/waveform for whatever's highlighted in Samples
   or Holding.
7. Assignments (`assignment_grid.py`'s `AssignmentGrid`) - P-6 bank/pad grid. Parked
   (`display = False`), same "Collect vs. Assign" two-screen direction as pane 1.

### Data model (`config_store.py`)

- `Pack` - name/description/timestamps + `holding: list[str]` (staged sample paths, not yet
  placed on a device). Device-agnostic.
- `Configuration` - wraps one `Pack` plus `assignments: dict[(bank, pad) -> path]`, which is
  P-6-specific.
- **Still one-to-one today**: despite "Pack" being its own dataclass, a `Configuration` is still
  exactly one `Pack` plus one device's worth of assignments in a single JSON file - the intended
  one-Pack-to-many-device-Configurations split (`docs/tasks/03-handling-multiple-devices.md`)
  hasn't been built. Don't assume it exists when reasoning about future device-support work.
- One JSON file per pack/configuration, slugified filename disambiguated on collision, no index
  file - `list_configurations` just reads the directory.
- Tag data and the preview cache (duration, wav format, waveform envelope, content hash) live
  separately in a sqlite db (`sample_store.py`, `tag_store.py`), keyed by sample path.

### Cross-widget communication

Most panes are siblings, not ancestor/descendant (they were split out of `MainColumn` into their
own columns - see `main_column.py`'s docstring), so they talk via Textual messages bubbled up to
`ShmampleApp`, which holds the `on_*` handlers wiring one widget's event to another's method
(app.py). Don't reach sideways between sibling widgets directly.

### Long-running work

Recursive scans/copies (`library_scan.scan_library`, `auto_tag.tag_folder`,
`config_store.export_holding`, `ConfigList._create_from_directory`) run via
`self.run_worker(..., exclusive=True, group="...", name="...")` wrapping an
`asyncio.to_thread(...)` call, never directly on the UI thread. Use `self.loading = True/False`
for a plain spinner, or a manual `border_subtitle` "N/total" string when the count itself is
useful progress a spinner would hide (see `FileBrowser._rescan_folder`'s comment). A test waiting
on one of these should scope to that specific worker `group` (see `_wait_for_export`/
`_wait_for_send` in `test_config_list.py`) rather than awaiting every worker in the app - unrelated
background workers (e.g. FileBrowser's own directory-loader) can get cancelled during ordinary UI
activity and fail a bare wait even though the one you actually care about finished fine.

### Folder picking

`widgets/directory_picker.py`'s `DirectoryPickerModal` is the only folder-choosing UI in the app -
reuse it rather than building another. `a` confirms the highlighted/current folder (not `ctrl+s`,
which most terminals treat as the XOFF flow-control character unless the user has run
`stty -ixon`).
