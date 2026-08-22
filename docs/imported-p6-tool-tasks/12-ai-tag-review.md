# Brief

Not building this yet - captured here so we don't lose the shape of it once
auto-tagging has been made more enthusiastic (see 13-folder-name-tagging.md)
and the tag list needs a cleanup pass.

Add a separate, optional feature that reviews the *tag vocabulary* (the
distinct tag names and their counts, same data TagBrowser already shows) with
Claude, rather than reviewing every sample's individual tag assignments.
Flags near-duplicates ("kick" vs "kicks" vs "Kik"), junk tags from bad
regex/folder-name matches, and suggests merges - not a per-sample correctness
check, that's a bigger, more expensive feature and out of scope here.

Auto-tagging itself must stay dependency-free and fully offline - this is
additive, not a replacement, and the base app must keep working with nothing
installed and no network access.

## Shape

- `tag_store.py`: new `rename_tag(old_name, new_name)` - a plain rename, or a
  merge (reassign every sample from the old tag to the target, then retire
  the old one) if `new_name` already names an existing active tag.
  `delete_tag` already exists for outright junk.
- A new module for the review call itself, importing `anthropic` lazily (only
  when the action actually runs) so the rest of the app never needs it
  installed. Sends the full `tag_counts()` list in one request - it's the
  vocabulary, not the samples, so this doesn't scale with library size.
  Structured output (`output_config.format`) for a validated list of
  suggestions: `{kind: merge|delete|rename, tag, target?, reason}`.
- A new action on the Tags pane (a key, not auto-triggered) that runs the call
  in a background worker with a loading indicator (same pattern as
  `action_auto_tag_cursor_node`'s folder walk), then shows the suggestions in
  a checklist modal (same shape as `ConfirmDeleteModal`/`ConfirmSendModal`) -
  accept or skip each one individually, nothing applied silently.
- `anthropic` becomes an optional dependency (its own extra in
  `pyproject.toml`), not a core one.
- Missing package, missing API key, or a failed call all just notify clearly
  and leave the tag list untouched - never crash the app or block ordinary
  (non-AI) tagging.

## Explicitly out of scope for this pass

- Reviewing/correcting individual sample-to-tag assignments (a bigger,
  separate feature - discussed and deliberately deferred further than this
  one).
- Any change to how auto-tagging itself decides what to tag - that's the
  other document.
