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
