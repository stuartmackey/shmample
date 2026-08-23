# aim

Make it easier for users to find duplicated samples either by filename or content.

Filename matching was tried and dropped: on a real ~69,000-file library it flagged ~29,000
"potential duplicates", of which 17,715 shared a name with no matching content at all - a
generic filename (e.g. "Kick.wav") recurring by coincidence across unrelated packs is not a
duplicate. Only content-hash matches count now (4,441 groups / 11,944 files on the same
library) - see "Handling duplicates" below.

# approach

Add a content hash into the database for each file that is ingested into the application. This can then be used to sccan and find duplicated hashes.

The hash is computed from decoded PCM sample data (via `wave.readframes`, the same read already done in `waveform.py`'s `load_waveform_peaks`), not the raw file bytes - this way two files carrying the same audio but different header/metadata still hash equal. Read and hash in chunks rather than loading the whole PCM buffer at once, for large files. This only matches bit-identical PCM - two files with the same audio at a different bit depth/sample rate still won't match, and that's fine, it's out of scope (would need audio fingerprinting).

# Current Gaps

- the content of sample is not current scanned until a user previews it
- a row is not added into the database until a user previews
- scanning the content of all samples on ingest will be  slow for large libraries

# Sub tasks

## filesystem stays the source of truth, database drives metadata

The sample browser keeps working the way it does today - a live scan of the filesystem drives what folders/files are shown. The database is not the list of what exists, it's an enrichment layer keyed on path: hash, duration/format, tags. When browsing, each file found on disk is joined against its database row if one exists; a file with no row yet is just shown without metadata (not scanned/hashed/tagged), same as an un-previewed file behaves today.

This must be implemented first before anything else can progress, since duplicate detection depends on every file having a hash row, not just the ones a user has happened to preview.

## Rescan

Rescanning a folder walks the filesystem and, for every file found, adds a database row if one doesn't exist yet (computing hash/format/duration). This is how new files get picked up and ingested. Triggered by the user when required, not automatic.

## Missing files

If a file is removed from disk, it simply stops appearing in the browser, same as today - the filesystem walk is what's shown, so there's nothing to reconcile at browse time. Its database row becomes orphaned (a path with no file behind it); this isn't a feature in its own right, just something a rescan should quietly clean up (remove orphaned rows, or at least exclude them from duplicate results) rather than something surfaced to the user as a "missing" state.

## Migrations

We will add a migration system so that updates to the schema can be performed without the user needing to remove and re add library locations

## Handling duplicates

When scanning the library locations, any duplicates (content-hash matches only, see "aim"
above) are given a tag of Potential-Duplicate.

A flat tag filter turned out not to be enough on its own at this scale (thousands of files,
no grouping, no way to compare candidates) - there is now a dedicated full-screen view
(`Shift+U`, `DuplicateReviewScreen` in `widgets/duplicate_review.py`) that lists each duplicate
group, lets the user preview/play each candidate, and permanently delete one. Deleting a file
removes it from disk and the database immediately, and un-tags whatever's left in that group if
fewer than 2 copies remain. No trash/recovery - deletion is permanent, by choice.

The tag itself is still useful as a filter/count in the main tag pane; the review screen is
where a duplicate actually gets resolved. If a duplicate was a false detection (extremely
unlikely now that it's content-hash-only, but possible - e.g. a corrupt file hashing to the
same digest as another corrupt file), removing just the tag rather than the file isn't
supported yet - tag removal is the next task, as before.

Not every content-hash match should be deleted, though - sample packs commonly put the same
hit in both a "Kits" folder and a separate individual-hits folder, deliberately. Rather than
try to infer that pattern from folder names (tried and rejected - too fragile, same lesson as
`auto_tag.py`'s naming-convention vocabulary), the review screen has an `a` "Allow" action: it
marks the group's content hash as an intentionally-kept duplicate (a small `allowed_duplicates`
table, added via the migration system above) and removes the tag from its files without
touching them. An allowed hash is excluded from all future duplicate detection, so a rescan
won't re-flag it. There's no "un-allow" UI yet if a decision needs reversing later.

## Performance

The new ingestion will be slow, we need to give progress, maybe show total sample count and how many have been ingested, updated as we progress
 
