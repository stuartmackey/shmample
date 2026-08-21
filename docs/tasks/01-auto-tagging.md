# aim

Add the ability for files to be tagged to make it easier to find specific types of sounds

# description

When selecting a file or folder, include a shortcut to "auto tag". Auto tagging works from
filename/folder naming conventions only for now (e.g. HH = High Hat, BD = Base Drum, per the
conventions used in "Samples From Mars" packs - still need to actually catalogue these before
writing the parser, see "auto tagging" below). Model- and audio-analysis-based tagging are both
deferred, not part of this pass.

Storage is SQLite (stdlib `sqlite3`, no new dependency) rather than the flat JSON files used
today - wanted for relational queries (tag counts, AND-filtering across tags). Existing
configuration storage (`settings.json`, `configurations/*.json`) moves into the same database
for consistency, rather than running two persistence mechanisms side by side. This is a bigger
change than the tagging feature on its own - see open questions below.

Preview information (duration, format, waveform envelope) is cached per sample path so browsing
can load it from the store instead of recalculating it on every highlight. Cache key is the
plain absolute file path, with no staleness check (mtime/hash) for now - simplest option,
accepted risk if a drive remounts elsewhere or a file moves; revisit if that turns out to bite in
practice.

# data model

- `tags`: id, name, soft-delete marker. Users can add, edit, and delete tags directly (not just
  via auto-tag). Deleting a tag from the tag list soft-deletes it and cascades a soft-delete to
  every `sample_tags` row referencing it (removes it from all samples at once). This is distinct
  from de-assigning a tag from a single sample, which only soft-deletes that one row and leaves
  the tag in place for every other sample still carrying it. A soft-deleted tag name is only ever
  revived by a manual assignment (a user typing/picking that name reassigns the existing
  soft-deleted row rather than creating a duplicate); an auto-tag rescan that would otherwise
  create or reassign a soft-deleted tag does nothing instead, treating a deleted tag as something
  the user has explicitly opted out of, not a gap to refill automatically.
- `sample_tags`: join table linking a sample path to a tag, plus an `origin` (auto | manual)
  marker and a soft-delete marker. Soft-delete (rather than a hard row removal) is what lets a
  rescan tell "never tagged" apart from "was tagged, user took it off" - a soft-deleted row is
  left alone by rescans rather than being recreated, so a manually removed auto-tag stays removed
  rather than reappearing on the next scan. Origin still separates auto-derived rows (safe for a
  rescan to add/refresh) from manual ones (never touched by a rescan at all).
- Sample preview cache: path, duration, format info, waveform envelope, stored in a display-size-
  independent form (see "waveform storage" below).

# functionality

- A dedicated tag pane (not a tab in the samples pane) - sized generously, since the tag list
  could get long.
- Lists every tag with a count of samples under it. Selecting a tag filters the sample list to
  matching samples, and narrows the tag list to only tags present in that filtered set.
- Multiple tags selected are AND'ed (must match all of them).
- A comma-separated text entry is also available for typing tags directly, as an alternative to
  selecting from the list.

# browsing: folder view vs flat list

The sample list can be toggled between the existing folder/tree view and a flat list showing just
file names, no folder grouping. Applies regardless of whether a tag filter is active, and within
whatever the current root scope is (the whole library, or a focused subfolder - see "focusing a
subfolder" below).

Duplicate filenames within the flat list (confirmed common in this library - see "the same
sample often exists two or three times" in the naming convention catalogue) aren't disambiguated
in the list itself. Instead, selecting/highlighting a file shows its full path in the preview
pane rather than just the filename, same place `PreviewInfo` already shows `path.name` today
(`widgets/preview_info.py:96`) - enough to tell duplicates apart without cluttering every row.

# browsing: focusing a subfolder

A shortcut (`.`, mirroring vim's convention for a repeat/dot-command style action rather than
overloading an existing key) on a folder narrows the current browsing scope to that subfolder -
the flat file list and the tag list (tags plus counts) both recalculate to cover only samples
under it, so the user can work within one sample pack instead of the whole library. This is a
view-level scope, not a change to the configured root paths from `11-sample-paths.md` - it
doesn't add or remove a samples directory, it narrows what's currently being browsed/counted
within the existing ones.

Leaving a focused subfolder reuses `h` (`cursor_parent`, already FileBrowser's "go up" key) -
pressed at the top of the current focused scope, where there's no parent node left to move to
within it, it pops the focus back out to the wider scope instead, one level at a time until back
to the full library. Same pattern `_DirsOnlyDirectoryTree.action_cursor_parent` already uses in
the folder picker (`widgets/directory_picker.py:38-54`): once the tree's own root is reached,
`h` re-roots one level up rather than becoming a no-op.

# auto tagging

- Bound to `t` in the samples pane. On a file it tags that one sample; on a folder it recursively
  tags every sample beneath it - folders themselves are never tagged (running it on a root
  samples directory is the way to tag a whole library). A folder run goes through
  `asyncio.to_thread` with a persistent loading spinner (same pattern as sending a configuration
  to the device), not a blocking call on the UI thread, since it can genuinely take a while.
  Tagging a file (or finishing a folder run) refreshes the tag pane's counts and, if the
  just-tagged file is the one currently shown, the preview pane's tags line too - both pick up
  the change immediately rather than waiting for the next highlight.
- Filename/folder naming convention only for this pass. Still need to go through the samples
  under `/run/media/stuart/Music/Samples From Mars/` to actually catalogue the conventions in use
  (HH, BD, etc. are examples, not the full list) before the parser can be written.
- Rescans never overwrite tags a user has since amended by hand. A rescan only ever inserts an
  `origin=auto` row for a (sample, tag) pair that has no existing row at all - if that pair is
  already present, whether still active or soft-deleted, the rescan leaves it as it is. Same rule
  applies to the tag itself: if the tag a rescan would apply has been soft-deleted, the rescan
  does nothing rather than reviving it. This is what stops a manually removed auto-tag (or a
  manually deleted tag) reappearing on the next scan, and it never touches `origin=manual` rows
  at all.
- A progress indicator is shown for every auto-tag run, whether it's one file or a whole folder -
  no special-casing the single-file case, it'll just finish and disappear quickly.
- Model-based tagging (shelling out to an installed command-line agent tool) and audio-content
  analysis are both explicitly deferred to a later task.

## naming convention catalogue

Surveyed the full library at `/run/media/stuart/Music/Samples From Mars/` (69,154 `.wav` files
across 33 packs, no other audio formats present). The "common naming convention" from the
original brief only covers part of the library - worth knowing before scoping the parser:

- **Drum-machine-style packs** (808/909/606/707/626/etc.) do use short instrument codes as the
  first word of the filename. Confirmed by frequency, most reliable first: `BD` Bass/Kick Drum
  (5,358 files), `SD` Snare Drum (4,045), `CH` Closed Hi-hat (3,132), `OH` Open Hi-hat (2,347),
  `HH` Hi-hat, generic (227). A longer tail of codes exist in much smaller numbers and are less
  certain without a pack manual to confirm against: `CP` Clap (31), `CB` Cowbell (21), `CY`
  Cymbal (20), `MA` Maracas (15), `LT` Low Tom (13), `MT` Mid Tom (8), `RS` Rimshot (7), `CL`
  Claves (7), `HT` High Tom (6), `MC`/`HC` (4 each, meaning unconfirmed).
- **Most of the library is not abbreviated at all.** The largest first-word counts overall are
  full words: `Tom` (5,723), `Conga` (2,194), `Clap` (1,924), `Ride` (1,136), `Cowbell` (1,081),
  `Rim` (876), `Snare` (774), `Crash` (762), `Timbale` (637), `Cymbal` (510), `Shaker` (498),
  `Bass` (452), `Cabasa` (442), `Tambourine`/`Tamb` (307/424), `Clave`/`Claves` (279/139),
  `Bongo` (268), `Maracas` (175), `Kick` (162), `Synth` (158), `Organ`/`Bell`/`Guitar`/`Triangle`
  (all under 100). A useful parser needs a vocabulary table (abbreviation and full word both
  mapping to the same canonical tag, e.g. `BD`/`Bass`/`Kick` all to "kick") rather than one
  abbreviation scheme.
- **Folder names carry real signal too**, sometimes the only signal: instrument-named folders
  (`07. Cabasa & Shaker/`, `06. Tom/`) label their contents even where the filename itself
  doesn't (`Cabasa MPC3000 Res.wav` sitting inside `07. Cabasa & Shaker/`), and synth/found-sound
  packs (`Synths/S612 From Mars/Chick N Swell/...`, `Found Sounds From Mars/WAV/Vortex/...`) have
  no recognisable instrument word in the filename at all - the aim's "naming of the file and
  folder structure" phrasing already anticipated needing both, this just confirms folder context
  is doing real work, not just a fallback.
- **Trailing tokens are not tags.** Numeric suffixes and velocity/round-robin indices (`BD 808 5
  MP1 G#.wav`) and note names on pitched synth samples (`...Vinyl Synths D#0.wav`) sit in the
  same position a tag might, so the parser needs to match against a known vocabulary rather than
  tagging every word in the filename.
- **The same sample often exists two or three times** under format-specific sub-folders within
  one pack (`WAV/`, `MPC1000 & MPC2500/`, `Maschine/` all containing their own copy of, say,
  `BD 808 Mi Cr A 5.wav`). Auto-tagging a whole pack folder will tag each copy separately, since
  they're genuinely separate files at separate paths - not a bug, just worth expecting inflated
  per-tag counts for packs shipped in multiple formats.

No pack ships a readme/manual documenting its own abbreviations, so the uncertain ones (`MC`,
`HC`, and to a lesser extent `CB`/`CL`/`RS`) are a judgement call rather than something to verify
against source material - fine to guess and correct later given tags can be edited by hand.

# waveform storage

Stored in a resolution/size-independent representation (a fixed, reasonably high-resolution
min/max envelope) rather than at whatever width `PreviewInfo`'s pane happened to be when it was
generated. Rendering becomes a separate downsampling step at display time, so the same cached
data serves any pane width.

# preview pane layout

Tags are appended ("Tags: ...") to the end of the date/duration/size line rather than getting a
row of their own - this pane is only a handful of rows tall, and the waveform is the part that
actually needs the vertical space. (A right-aligned spot on the wav-format line was tried first
but didn't work out.)
