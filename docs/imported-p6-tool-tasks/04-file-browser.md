# Brief

- This will be a list of folders and files with the starting point being a configured samples directory
- Shows only valid items (See below)
- Pressing return on a folder opens it to show contents
- sub folder content is indented
- Pressing return on an open folder colapses the contents


# Valid Items

- Subfolder
- WAV files

# Feasibility check against Textual's `DirectoryTree`

Checked with a throwaway spike (temp dir with a top-level `.wav`, a `.txt` file, and a nested folder containing a mixed-case `snare.WAV` and a `readme.md`), and it's a strong match — most of this brief is `DirectoryTree`'s existing behaviour, not custom code:

- **Filtering to valid items** — `DirectoryTree.filter_paths(paths)` is exactly this extension point: override it to keep directories and `.wav` files (case-insensitive suffix check). Confirmed `notes.txt`/`readme.md` were excluded and `snare.WAV` (mixed case) was kept.
- **Expand/collapse on Enter** — `Tree.auto_expand` defaults to `True`, so selecting (Enter) a directory node toggles it expanded/collapsed for free; selecting a file node instead fires a `FileSelected` message. Confirmed: pressing Enter on the `Drums` node expanded it (children became visible), pressing Enter again collapsed it.
- **Indentation of subfolder content** — built into `Tree`'s rendering (indent guide per depth), no custom layout needed.
- **Sort order** (not specified in the brief, worth confirming) — `DirectoryTree`'s default loader sorts directories before files, then alphabetically case-insensitive within each group. Matched in the spike (`Drums` listed before `kick.wav`).
- **Lazy loading** (a free bonus, not in the brief) — subdirectory contents are only loaded (via a background worker) when a node is actually expanded, not scanned upfront. Matters for large sample libraries.

**Recommendation**: replace the current hand-rolled `ListView`-based `FileBrowser` with a `DirectoryTree` subclass overriding `filter_paths`, rather than building tree/indent/expand logic by hand.

## Gaps - decided

1. **Empty-of-valid-content folders** — ~~show but empty~~ **superseded**: now hidden entirely. See "Hiding folders with no valid content" below - the recursive check this originally avoided turned out to be wanted after all.
2. **`a` (assign)/`p` (preview) on a highlighted folder** — both do nothing. Only meaningful on a highlighted file.
3. **Enter on a file** — previews it. `DirectoryTree`'s built-in `FileSelected` message (already fires on Enter-select of a leaf node, no custom handling needed to detect it) drives this, in addition to the existing `p` key.
4. **Vim keys** — confirmed: re-add against `Tree`'s actual action names (`cursor_up`/`cursor_down`/`cursor_parent`/`toggle_node`), not `DataTable`/`ListView`'s. `Tree` has no left/right cursor concept, so `h`/`l` map to `cursor_parent`/`toggle_node` rather than a direct equivalent of `cursor_left`/`cursor_right`.

Implemented in `src/p6_tool/widgets/file_browser.py` — `FileBrowser` is now a `DirectoryTree` subclass rather than a `ListView`. `p`/Enter both record `last_previewed` (no audio backend to actually play it yet — that's the phase-3 spike from `02-implementation-plan.md`). `a` (assign) stays entirely unwired, since there's no assignment grid pane to assign to — a stub there would have no effect at all.

## Icons

Default `DirectoryTree` icons (📁/📂/📄) are colour emoji — the colour is baked into the terminal's emoji font and ignores Rich/CSS styling entirely, which is why they always look "coloured" regardless of theme. Swapped `ICON_NODE`/`ICON_NODE_EXPANDED`/`ICON_FILE` for Nerd Font glyphs (folder/folder-open/file-audio from Font Awesome, ``/``/``) — plain text characters, so they inherit whatever colour the existing `directory-tree--folder`/`directory-tree--file` component styles give them (currently just the theme's normal foreground, same as the rest of the text) instead of a fixed hue. Only one file icon needed since `filter_paths` means every visible file is already a `.wav`.

**Depends on the terminal font actually being Nerd Font-patched** — without one, these render as blank boxes/tofu instead of folder/file glyphs. Not verifiable from here (screenshots render via Rich's own text layout, not the real terminal's font), so worth an actual look via `mise run tool` to confirm the glyphs show up as intended.

## Preview info pane

Decision: a small info pane at the bottom of the file browser's own column (not a separate pane elsewhere in the layout), about 1/5 of that column's height, the tree taking the rest. Shows, for whatever's highlighted:

- creation date
- the static waveform (see `05-audio-preview.md` for the rendering approach and how it stays legible at this size)
- **future**: tags, once the tagging feature exists (not building this now - see below)

### Tags (future feature, noted for later)

Idea floated: let samples be tagged for searching/filtering, with tags shown in this same info pane once they exist. Not designed or scoped yet - no data model, no storage location, no UI for assigning a tag decided. Flagging here only so the info pane's layout doesn't need to be redone later to make room for a third piece of content; the tagging feature itself is a separate future task.

### Implemented

`FileBrowserColumn` (`src/p6_tool/widgets/file_browser_column.py`) is a `Vertical` stacking `FileBrowser` (4fr height) over `PreviewInfo` (1fr height, ≈1/5 - confirmed empirically at 32/8 rows for a 40-row terminal), each with its own bordered pane. Wired via `Tree.NodeHighlighted`, which fires as the cursor moves (not just on Enter/`p`) - so the pane updates live while browsing, showing the highlighted file's name+date and waveform, or clearing for a folder/nothing. `P6ToolApp` now composes `FileBrowserColumn` instead of `FileBrowser` directly. This closes off the file browser's current scope - covered by `tests/test_file_browser.py`, `tests/test_preview_info.py`, and `tests/test_waveform.py`.

## Hiding folders with no valid content

Revisited decision 1 above. Implemented the recursive-with-early-exit check that was flagged as the cost of doing this: `_contains_wav(path)` in `src/p6_tool/widgets/file_browser.py` walks a folder's subtree via `os.scandir`, returning `True` as soon as it finds one `.wav` anywhere below - not a full walk in the common case, but a folder with genuinely nothing valid inside still needs its whole subtree scanned to prove that, same trade-off as originally described.

`filter_paths` now keeps a directory only if `_contains_wav` finds something, instead of keeping every directory unconditionally. Tested with a folder that has a `.wav` only two levels down and nothing directly inside it (`Nested/Sub/tom.wav`), confirming the check is genuinely recursive rather than a peek at immediate children, plus the reverse case (a folder with only a `.txt` file anywhere inside is hidden entirely, where it was previously shown-but-empty).

## Narrower scrollbar

`Widget`'s own default is `scrollbar-size-vertical: 2` (columns) / `scrollbar-size-horizontal: 1` (rows) - vertical was the wide one and the relevant one here, since the tree only really scrolls vertically. Set to `1` via `FileBrowser`'s own `DEFAULT_CSS`, confirmed visually with 30 sample files forcing a scrollbar to appear - one column wide instead of two.
