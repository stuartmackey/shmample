# Brief

The pad-assignment pane: the remaining module from `02-implementation-plan.md`'s TUI phase - the settled design from `03-skeleton-tui.md`'s spike ("hybrid grid + submenu") had never actually been built against real data.

# Implemented

## Layout

`P6ToolApp.compose()` now wraps `MainColumn` and the new `AssignmentGrid` in a `Horizontal` (both get `width: 1fr`, `MainColumn` capped at `max-width: 33%` as before), with `Footer()` as a third top-level sibling. Numbered pane jump extended: `5` → `#assignments`, border title `[5] Assignments`.

## `AssignmentGrid` (`src/p6_tool/widgets/assignment_grid.py`)

A `DataTable` subclass, 8 rows (bank `A`-`H`, row label = the letter) x 6 columns (pad `1`-`6`), reusing `device.PAD_NUMBERS` rather than redefining it. Each cell shows the assigned sample's filename or `-`. Columns are a fixed 14 chars wide (`PAD_COLUMN_WIDTH`) rather than content-fitted - `update_cell()` defaults to `update_width=False`, so a column sized to the `"1".."6"` header would've clipped every real filename to one character. Found this by actually screenshotting the running app, not just from reading the DataTable docs.

Row order is `device.BANK_DISPLAY_ORDER` ("AEBFCGDH"), not alphabetical `BANK_LETTERS` - the real device only has 4 physical bank buttons, each cycling between two banks (A/E, B/F, C/G, D/H), so grouping the grid by that pairing puts each button's two banks next to each other rather than scattered across an alphabetical A-H list. `BankPickerModal`'s option order follows the same sequence. `BANK_LETTERS` itself is untouched (still the canonical alphabetical set, e.g. for anything that needs to validate/enumerate bank names rather than display them).

Cursor-navigable (arrows natively, plus vim `h`/`j`/`k`/`l` merged in the usual way). Single-key actions on whichever pad the cursor is on:

- `d` - clear the assignment
- `p` - preview the assigned sample (same `Previewer`/`run_worker` pattern as `FileBrowser`)
- `i` - show it in the `PreviewInfo` pane (queried cross-column via `#preview` - `query_one` isn't scoped to siblings, so this works despite `AssignmentGrid` and `PreviewInfo` living in different branches of the tree)
- `s` - save. If nothing's loaded yet (`configuration_path is None`), reuses `ConfigList`'s own `NewConfigurationModal` to prompt for a name/description, same as `n` does there; otherwise just re-saves in place and bumps `modified_at`.

`AssignmentGrid` always holds a working `Configuration` - a blank unsaved one from construction, or whatever `load()` was last given - so assigning pads before ever opening or naming a configuration works fine; `s` is what turns that into a named, persisted one.

## Creating an assignment: the file browser's `a` chord

`FileBrowser` gained `a` (`action_start_assign`), guarded the same way as `p`/preview (must be a highlighted file, not a folder). Pushes `BankPickerModal`, then `PadPickerModal`, then calls `AssignmentGrid.assign(bank, pad, path)` directly via `self.app.query_one("#assignments", AssignmentGrid)`.

### Deviation from the spike: modals instead of a hand-rolled on_key submenu

`03-skeleton-tui.md`'s settled design was an in-place status-pane submenu, explicitly *not* a `ModalScreen`, and flagged a real gotcha for whichever approach got built for real: a focused widget's own key bindings fire even while some other input-mode state machine is also watching for the same keypress ("bound keys still bubble").

Built it as two `ModalScreen`s instead (`BankPickerModal`/`PadPickerModal` in `assignment_grid.py`), reusing the pattern `ConfigList`'s `NewConfigurationModal`/`ConfirmDeleteModal` already established, rather than the spiked in-place submenu, for two reasons:

- There's no status/log pane in the pane layout that actually got built (`MainColumn` stacks device/configs/files/preview) for an in-place submenu to live in - the spike's 2x2-grid-with-a-status-quadrant layout isn't the layout this app ended up with.
- A pushed `ModalScreen` becomes the app's active screen and owns input exclusively - the widget underneath (`FileBrowser`, its own `j`/`k`/`h`/`l`/`p` bindings) doesn't see keys at all while the modal's up, which sidesteps the bubbling gotcha entirely rather than needing to work around it.

Each picker still matches the brief's "A then 1" idea directly rather than falling back to arrow-navigate-then-enter: every valid letter/digit is *also* its own direct `Binding` on the modal (`Binding("e", "pick('E')", ...)`), so pressing it alone picks it immediately. The `OptionList` (via the same `VimOptionList` `ConfigList`'s modals use, pulled out to `widgets/vim_option_list.py` so both can share it) is there for visual discoverability and an arrow+enter alternative, not the primary path.

One known minor gap from this choice: `BankPickerModal` only binds `a`-`h`, so a stray digit pressed at that step (before a bank's been chosen) falls through to the App's own pane-jump bindings (`1`-`5`) rather than being swallowed - focus can shift to another pane while the modal's still open waiting for a letter. Not fixed - low severity (nothing crashes, `escape` still cancels correctly) and out of scope for getting the core flow working.

## Wiring configs <-> the grid: messages, not cross-imports

`ConfigList` (owns configs) and `AssignmentGrid` (owns the grid) are siblings under different parents (`MainColumn` vs. the top-level `Horizontal`), not ancestor/descendant - so neither can just reach into the other via `query_one` without also importing the other's module, and `AssignmentGrid` already needs to import `NewConfigurationModal` from `config_list.py` for `s`'s prompt-for-a-name flow, so having `config_list.py` import `assignment_grid.py` back would be circular.

Solved with two plain Textual `Message`s bubbled up to `P6ToolApp`, which is the one place that already knows about both:

- `ConfigList.Opened(path, configuration)` - posted from `on_list_view_selected` (alongside the existing `last_opened` bookkeeping, unchanged) whenever Enter opens one. `P6ToolApp.on_config_list_opened` forwards it into `AssignmentGrid.load()`.
- `AssignmentGrid.Saved` - posted after `action_save` succeeds. `P6ToolApp.on_assignment_grid_saved` calls `ConfigList.refresh_list()` so a newly-saved (or re-saved) configuration shows up in the list immediately.

# Tests

29 more tests across `test_assignment_grid.py` (new) and `test_pane_jump.py` (extended for `5`), 123 total:

- Grid mechanics: starts all-empty, `assign()`/`load()`/`d`/`p`/`i` in isolation (a standalone `AssignmentGridApp`, not the full `P6ToolApp`), last-assignment-wins on a repeated pad.
- `s` with nothing loaded (prompts, saves, `configuration_path` gets set), already-loaded (re-saves in place, one file not two), and cancelled (saves nothing).
- Bank/pad picker modals directly: a letter/digit key picks immediately, `escape` cancels.
- The full chord end-to-end through `P6ToolApp`: `a` → `e` → `4` assigns the highlighted sample; `escape` at either step assigns nothing.
- Cross-pane wiring: opening a configuration loads it into the grid; saving from the grid refreshes the configuration list; `5` focuses the grid.

Confirmed visually too (screenshot of a running `P6ToolApp`, not just the test suite) - caught the column-width truncation bug above, which no test would have caught since `get_cell()` returns the untruncated stored value regardless of the rendered column width.

# Rows/columns stretch to fill the pane

`DataTable` sizes rows/columns to content (or a fixed `width=`) by default and leaves the rest of the widget blank - on a typical terminal the 8x6 grid only used a fraction of the height it was given. `AssignmentGrid._layout_grid()` now computes a row height (`available height / 8`) and column width (`available width / 6`, floored at `MIN_PAD_COLUMN_WIDTH` so it never shrinks back to the original truncation bug) from `self.size`, then rebuilds the table (`clear(columns=True)` + re-add) with those - `DataTable` has no public API to resize an existing row/column in place. Cell contents come back from `self.configuration` via the existing `_refresh_cells()`; cursor position is saved/restored across the rebuild.

Runs from `on_mount()` and again from `on_resize()`, so live terminal resizing re-fits the grid rather than only sizing it once at startup.

Two things only found by actually measuring the running widget, not from reading the `DataTable` docs:

- `events.Resize.size` turned out to report the widget's *outer* (bordered) size, 2 cells wider/taller than `self.size`'s content-box size - using it directly would have sized every row/column 2 cells too generously. Fixed by reading `self.size` fresh inside `_layout_grid()` instead of trusting the event's own `size` attribute.
- `add_column(width=...)` sets the column's *content* width, but `cell_padding` (1 by default) is added on each side on top of that when rendering - so the actual on-screen column is `width + 2` cells, not `width`. The available-width-per-column budget has to account for that padding before being handed to `add_column`, or the grid overflows/underfills by 2 cells per column.

3 more tests, 126 total: rows/columns actually grow past their floor on a large terminal, columns clamp to the floor (not shrink further) on a narrow one, and a live resize via `pilot.resize_terminal` re-lays-out the grid while both the cell data and cursor position survive the rebuild.

# Not yet built

- Device transfer (`02-implementation-plan.md`'s **Device transfer** module) - actually copying assigned samples onto a mounted P-6's `IMPORT/BANK_X/PAD_Y/`, missing-file validation before a commit, and the post-copy "confirm on the device" prompt. This pane only edits/saves assignments; nothing here touches the device yet.
- The `BankPickerModal` stray-digit-falls-through-to-pane-jump gap noted above.

# Multi-select assign: whole tracks into a whole bank

Requested addition: select several samples in the file browser at once, then assign the *set* to a bank in one go, pads filled in the order they were picked - rather than repeating the single-file `a` chord per pad. Explicitly meant to replace, not merge with, whatever was already in that bank.

- `FileBrowser` gained a `selected: list[TreeNode]` (ordered, not a `set` - pad order follows pick order, not tree/alphabetical order) and `space` to toggle the highlighted file in/out of it. `space` was already bound by `Tree`/`DirectoryTree` to `toggle_node` (expand/collapse) - re-bound entirely rather than added alongside, so `action_toggle_select_or_node` explicitly falls back to `self.action_toggle_node()` for a folder (that behaviour would otherwise be lost, not merely shadowed) and only toggles selection for a leaf file.
- Selected files are shown via a `render_label` override (wrapping whatever `DirectoryTree.render_label` already produces) - `TreeNode.refresh()` (a small, public, single-line repaint - not the same as `Tree._invalidate()`'s full-tree private one used elsewhere) is enough to make the toggle show up immediately. First cut prefixed a `✓ ` marker; changed on request to `label.stylize("bold green")` (recolouring in place) instead - a prefix shifts every filename in the tree a couple of columns right the moment a selection changes, which reads as the list itself moving rather than a selection state changing.
- `action_start_assign` (the existing `a` handler) now branches on `self.selected`: non-empty skips straight to a *bank-only* `BankPickerModal` (no pad step - there's nothing to ask, every pad's getting filled) and calls the new `AssignmentGrid.assign_many(bank, paths)`; empty falls through to the original single-file bank-then-pad flow, unchanged. `BankPickerModal.__init__` was generalised from always taking a bare sample name (auto-quoted) to a pre-formatted `description` string, so the same modal can read naturally as either `Assign 'kick.wav' -> bank` or `Assign 3 selected samples -> bank`.
- `AssignmentGrid.assign_many()` clears *all 6* of the target bank's pads first (per "remove any previous assignments"), then fills from pad 1 via `zip(PAD_NUMBERS, sample_paths)` - which also caps it at 6 if it's ever handed more, no manual slicing needed. Kept as a defensive floor even though nothing can reach it through the UI now (see below) - `assign_many` is a public method, called directly in tests, and shouldn't assume its caller already enforced the limit.
- Selection is cleared (list + every node's marker refreshed) once the bank's chosen and the assignment's gone through; cancelling the bank picker (`escape`) leaves the selection intact, in case the user wants to retry a different bank.

**Capped at selection time, not assign time** - first cut let you select as many as you liked and only warned/truncated when `a` was pressed; changed on request to refuse a 7th `space` outright (`action_toggle_select_or_node` checks `len(self.selected) >= len(PAD_NUMBERS)` before appending), with `self.app.notify(..., severity="warning")` firing immediately rather than after the bank's already been picked. Deselecting one always frees a slot for another. This made the equivalent check in `_start_assign_selection` unreachable (`paths` can never exceed 6 by the time a bank's chosen) - removed rather than left as dead code.

12 more tests, 138 total: select/deselect toggling and its marker, `space` still expanding a folder instead of "selecting" it, the 7th-selection refusal (and that deselecting one reopens a slot), `assign_many` in isolation (fill order, clearing pre-existing pads, still capping at 6 if called directly with more), and the full chord end-to-end (selection order honoured, markers cleared after, a pre-existing assignment in the target bank actually gets replaced, and the cursor sitting on an unselected file doesn't leak into the multi-assign).

# Focused-pane border highlight

None of the five panes changed appearance on focus - `DevicePanel` especially was "no obvious [indication]" per feedback, but the fix applies to all of them for consistency, not just that one.

Added a `:focus` CSS rule alongside each pane's existing `border: round $foreground` - `border: round $primary` (resolves to `ansi_blue` under the ansi themes, distinct from `$foreground`'s `ansi_default` and from `$success`/`$error`'s `ansi_green`/`ansi_red` already used elsewhere for the config modals). `ConfigList`/`FileBrowser`/`PreviewInfo`'s rules live in `MainColumn`'s `DEFAULT_CSS` (that's where their base `border: round $foreground` already lived, keyed off `MainColumn > Widget` selectors); `DevicePanel`/`AssignmentGrid` each get their own since they're not nested under `MainColumn`.

1 more test (`test_pane_jump.py`), 139 total: focuses each of the five panes in turn and checks its border colour differs from every other (currently-unfocused) pane's. Confirmed visually too - `widget.styles.border_top` reports `ansi=4` (blue) only for whichever pane currently holds focus, `ansi=-1` (terminal default) for the rest.

# Bug: assignments could be made (and silently lost) without an active configuration

Reported: assignments weren't showing up in the saved configuration, and it was possible to assign samples with no configuration picked at all. Root cause was the second thing causing the first: `AssignmentGrid` always held *some* `Configuration` from construction (`_blank_configuration()`, an unnamed in-memory scratch object with `configuration_path=None`), so assigning was always possible regardless of whether the user had opened or created anything in `ConfigList`. `s` on that scratch state prompted for a name and saved a fresh file - but if the user had *already* picked "n" or Enter'd an existing configuration expecting to assign into that one, the grid could still be sitting on the disconnected scratch object instead (nothing forced the two to line up), so the assignment landed in a configuration the user never saw and didn't ask for.

Fixed by requiring an active configuration up front rather than falling back to a scratch one:

- `AssignmentGrid.configuration`/`configuration_path` are now both `None` until `load()` is given a real `(path, Configuration)` pair - `_blank_configuration()` is gone. `load(None)` now means "deactivate" (both `None`), not "reset to a new blank one".
- `assign()`/`assign_many()`/`action_clear_cursor_pad()`/`action_preview_cursor_pad()`/`action_info_cursor_pad()` all guard on `self.configuration is None` and no-op rather than raising.
- `action_save()` lost its "prompt for a name and create one" branch entirely - naming is `ConfigList`'s job (`n`), not this pane's. It now either re-saves the active configuration in place, or (`configuration is None`) notifies "No active configuration to save." and does nothing.
- `FileBrowser.action_start_assign` checks `AssignmentGrid.configuration is not None` before starting the bank/pad chord at all (single or multi-select) - if nothing's active, it notifies "Pick or create a configuration before assigning samples." and never opens a picker.
- `ConfigList.action_new_configuration` ("n") now posts `ConfigList.Opened` after saving, the same message Enter already posts - a brand new configuration becomes the grid's active one immediately, so there's no gap where you've "created" one but still can't assign to it without a separate Enter.

**A `check_action`-based approach (hiding `a`/`s`/etc. from the footer when inactive, matching `DevicePanel`'s `u`/`m` pattern) was tried first and reverted** - `check_action` returning `False` blocks the *keypress* from ever reaching the action method (confirmed by reading Textual's `_check_bindings`/`run_action` source, not just assumed), which meant the in-method `notify()` calls could never actually fire. Since the whole point here was surfacing *why* the action didn't happen, not just hiding it, the runtime guards above are the only gate - no `check_action` overrides on either widget for this.

6 more tests, 143 total: `assign()`/`assign_many()` are no-ops with nothing active, `s` notifies instead of prompting when nothing's active, `a` notifies and opens no picker when nothing's active, `load(None)` deactivates rather than resetting to blank, and "n" makes a brand-new configuration immediately assignable. Every existing test that called `grid.assign()`/pressed `a` directly needed a `_activate_configuration()` helper call added first, since none of them had an active configuration under the old always-available scratch state. Confirmed end-to-end outside the test suite too: assign-with-nothing-active refuses and notifies, `n` then assign then `s` round-trips to disk correctly.

# Removed "s" - assignments autosave instead

Feedback: a user assigning entirely from the file browser's `a` chord (which is the whole point of the multi-select feature above) might never actually visit the Assignments pane at all, so an `s` binding that only exists there is easy to never discover. There was also a real ambiguity in what `s` even meant - "save" reads as either "the pad I'm looking at" or "the whole configuration" (it was always the latter, but the key gave no reason to assume that).

Fixed by removing `s`/`action_save` entirely and writing to disk on every mutation instead:

- `assign()`, `assign_many()`, and `action_clear_cursor_pad()` each call a new private `_save()` at the end (only if something actually changed, for the clear case - clearing an already-empty pad still doesn't write anything). `assign_many()` writes once per call, not once per pad, despite touching up to 6 assignments.
- `_save()` is what `action_save` used to be minus the "no active configuration" branch's user-facing notification - since every call site already only reaches it once `self.configuration`/`configuration_path` are confirmed set, there's nothing left to warn about.
- `AssignmentGrid.Saved` is now posted after every autosave rather than an explicit key, so `ConfigList` still refreshes live as assignments come in - confirmed by a test that assigns into a configuration ConfigList doesn't know about yet (created directly on disk, not via "n") and checks it appears in the list with no explicit save step.

3 tests changed from pressing `s` to asserting the write happened immediately after `assign()`/`d` alone, 143 total (net unchanged - one `s`-specific test was removed as no longer meaningful, one new one added for `d` autosaving). Confirmed live outside the suite too: created a configuration, assigned a sample purely from the file browser without ever focusing or pressing anything in the Assignments pane, and the assignment was already on disk.

# Feature: each pad shows its sample's size

Requested once `09-save-assignments.md`'s device-transfer work made file size actually matter (samples add up against the P-6's small IMPORT partition) - the grid itself never showed how big anything was, only its filename.

- `AssignmentGrid._cell_text(sample_path)` - a new shared helper `_refresh_cells()`/`assign()`/`assign_many()` all now build their cell content through - returns `"-"` for an empty pad, `"{filename}\n{device.human_bytes(size)}"` for an assigned one (filename on its own first line, size on a second line beneath), or just the bare filename if the file's gone missing (`stat()` raising `OSError` - same "don't crash over a display concern" spirit as `send_configuration`'s own missing-source handling, just here it's shown, not skipped).
- `MIN_ROW_HEIGHT = 2` added alongside the existing `MIN_PAD_COLUMN_WIDTH` floor, and `_layout_grid()`'s row-height calculation now floors at it instead of `1` - `DataTable` top-aligns cell content, so a single-line row would just clip the new size line off entirely rather than wrapping or scrolling it into view.

2 more tests, 181 total: `assign()` showing a real file's size on the second line (checked with `device.human_bytes()`, not a hardcoded string, so it can't silently drift from the actual formatting logic) and falling back to the name alone for a missing file. Every pre-existing test that compared a cell's content to a bare filename (`get_cell(...) == "kick.wav"`) needed a small `_cell_name()` test helper (splits off the first line) substituted in throughout `test_assignment_grid.py`, since those cells now carry a size line too - a mechanical, file-wide change rather than a behavioural one for any of them.
