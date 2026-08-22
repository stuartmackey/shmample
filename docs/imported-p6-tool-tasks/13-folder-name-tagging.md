# Brief

Auto-tagging only ever looked at a sample's filename and its immediate
parent folder, matched against a fixed instrument vocabulary (kick, snare,
hihat, ...). Packs are usually sold with the pack/vendor name somewhere in
the folder hierarchy above that, which the tagger ignored entirely -
finding "everything from this pack" meant browsing the tree, not tagging.

Decided against tagging every ancestor folder unconditionally (too noisy -
"Kicks", "WAV", "Kontakt" all become tags shared across unrelated packs) and
against picking one fixed nesting depth as "the pack level" (real libraries
vary too much - sometimes a vendor layer above the pack, sometimes none).

Landed on: walk the folder names between a sample and whichever root it's
being browsed under (a configured samples directory, or a "."-focused
subfolder - see `FileBrowser._root_for`), favouring the ones closest to that
root over deeper ones, since deeper folders tend to be file-type or
DAW-export folders rather than pack identity. Capped at `MAX_FOLDER_TAGS`
(2) folder tags per sample, and a short, deliberately non-exhaustive
blocklist (`_GENERIC_FOLDER_WORDS` in `auto_tag.py`) skips folder names that
are obviously not pack names (file formats, bit depths, common DAW/plugin
folders).

Leaning generous rather than conservative here on purpose - the eventual
tag-vocabulary review (12-ai-tag-review.md) is what cleans up whatever this
gets wrong, so this doesn't need to be precise, just cheap and mostly right.

See `auto_tag.tags_for_path` (instrument tags plus folder tags) and
`auto_tag.tag_file`/`tag_folder`'s new `root` parameter.
