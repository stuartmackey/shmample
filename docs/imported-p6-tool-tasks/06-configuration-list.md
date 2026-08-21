# Brief

This will be a new panel, sitting in the same vertical column as the file browser - much like lazygit's branches-above-files layout, not a separate quadrant.

# Functionality

List existing configurations
Delete existing configuration
Add configuration

# Configuration Details

Name
Description
Created Date
Modified Date
Pad Assignements
  Bank
  Pad
  Sample Path / Filename

# Implementation

A json file per configuration, rather than one large file listing them all. No parent index file - the pane lists whatever's in `~/.config/p6-tool/configurations/` directly, simpler than keeping a manifest in sync with the actual files on disk.

# Keybindings

n - new configuration
d - delete selected (with confirmation)
enter - select / open configuration to allow changes

# Decisions (from review)

- **Layout**: configs, file browser, and preview info all stack in the same column, lazygit-style. Height split not pinned down precisely yet - working assumption is configs 1fr / file browser 3fr / preview info 1fr (≈1/5 : 3/5 : 1/5, keeping the original "1/5" for configs and preview, splitting the remainder to the file browser), open to adjustment once it's actually built and visible.
- **`Configuration` data model update needed** (`02-implementation-plan.md`): add `modified_at`, updated on every save.
- **Naming**: `name`, not `Title` - matches the existing data model.
- **Storage**: no parent index file - list configurations by reading the directory.
- **Delete**: `d` asks for confirmation before deleting (the brief's "(with configuration)" was a mistype for "(with confirmation)").
- **New configuration** (`n`): opens a modal to type in name and description - similar to lazygit's commit-message modal.
- **Selecting a configuration** (cursor movement, before Enter): the pad-assignment pane (not yet built) shows a details view of the highlighted configuration - name, description, dates, its assignment list. Same "live preview as you move the cursor" pattern `PreviewInfo` already uses for the file browser.
- **Opening a configuration** (`Enter`): replaces that details view with the actual editable pad-assignment grid for that configuration, loaded from its JSON file.
- The last two points depend on the pad-assignment/grid pane, which doesn't exist yet - captured here so the keybindings are settled, but the wiring itself waits until that pane is built.

# Implemented

- `src/p6_tool/config_store.py` — `Configuration` dataclass (`name`/`description`/`created_at`/`modified_at`/`assignments`, the last a `dict[(bank, pad), sample_path]`, serialised as a list of `{bank, pad, sample_path}` records since JSON object keys can't be tuples). `list_configurations`/`save_configuration`/`delete_configuration` - no parent index, filenames are the slugified name with a numeric suffix on collision (`kit.json`, `kit-2.json`, ...). Corrupt/unparseable files are skipped rather than crashing the pane.
- `src/p6_tool/widgets/config_list.py` — `ConfigList(ListView)`: vim `j`/`k`, `n` opens `NewConfigurationModal` (name + description, blocks on empty name), `d` opens `ConfirmDeleteModal`, `Enter` sets `last_opened` (still just a recorded hook, per the deferred item above - no assignment grid to load it into yet). Shows a placeholder row when there are no saved configurations.
- `src/p6_tool/widgets/main_column.py` (renamed from `file_browser_column.py`, since it now holds three panes, not one) — `MainColumn` stacks `ConfigList` (1fr) / `FileBrowser` (3fr) / `PreviewInfo` (1fr). Confirmed empirically at 8:24:8 rows for a 40-row terminal, matching the ≈1/5:3/5:1/5 target.
- Test-isolation note: `P6ToolApp`/`MainColumn`/`ConfigList` all resolve a `None` `configurations_dir` to `config_store.DEFAULT_CONFIGURATIONS_DIR` **at call time** rather than as a mutable default parameter, specifically so `tests/conftest.py`'s autouse fixture can monkeypatch that constant and guarantee no test ever touches the real `~/.config/p6-tool/configurations`. A plain default-parameter value would have bound the real path once at import time, before any fixture could intervene.
- 25 new tests (`test_config_store.py`, `test_config_list.py`), 57 total in the suite, all passing. Confirmed visually too - two saved configurations listed alphabetically above the file browser.

## Modal styling, lazygit look

Both modals restyled to match reference screenshots rather than the initial Label+Button layout:

- `NewConfigurationModal` - two titled/bordered boxes (`Widget.border_title`, rendered directly into the border line, e.g. `─Name─`) instead of `Label` + `Input` pairs, no visible buttons. Name stayed a single-line `Input` (Enter submits); description became a multi-line `TextArea` (Enter inserts a newline instead, since a description can reasonably be more than one line) - `ctrl+s` submits from either field, hint shown in the description box's `border_subtitle`. Border colour is `$success` (resolves to `ansi_green` under the ansi themes), capped at `max-width: 33%` per feedback that 90% width looked too wide.
- `ConfirmDeleteModal` - replaced Label+Buttons with an `OptionList` (`_VimOptionList`, adding `j`/`k` same as everywhere else) showing "Delete '<name>'" and "Cancel" as selectable options, with a lazygit-style `border_subtitle` position indicator ("1 of 2") that updates via `OptionList.OptionHighlighted`, plus a second bordered box below showing detail text for whichever option is currently highlighted. Border colour `$error` (→ `ansi_red`), matching the destructive nature of the action.
- 4 more tests covering the new modal's keyboard-driven flow (navigate to "Cancel" and confirm nothing is deleted, detail text switches with the highlighted option), 59 total.

## Numbered pane jump (lazygit-style)

`1`/`2`/`3` jump focus directly to Configurations/Samples/Preview, added as `P6ToolApp`-level `BINDINGS` with an `action_focus_pane(selector)` taking a widget selector argument (Textual's `Binding` action strings support call-argument syntax, e.g. `"focus_pane('#files')"`). Works as a *global fallback* - Textual resolves key bindings by checking the focused widget's own `BINDINGS` first and only walks up to the App if nothing closer claims the key, so this doesn't clash with `ConfigList`/`FileBrowser`'s own bindings (neither uses digit keys). Each pane's `border_title` now also carries the matching `[N]` prefix (e.g. `[1] Configurations`), matching the reference screenshot. `PreviewInfo` needed `can_focus = True` added - it has no bindings of its own, but needs to be a valid focus target for `3` to land on.

Not yet relevant, but worth remembering when the assignment grid exists and introduces bank/pad chord input: digit keys will then be doing double duty (pane jump vs. pad-number entry mid-chord), the same tension already flagged in `03-skeleton-tui.md` - the chord-priority-first ordering documented there is the pattern to reuse.
