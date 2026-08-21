# Brief

Create a skeleton TUI to set up tooling, development environment and then provide framework for any spikes that are necessary

# Considerations

- `mise run setup` command to initialise dev environment, install dependencies
- `mise run tool` to execute tui for experimentation

# Library spike: Textual

Confirmed with a throwaway spike (2x2 `Grid` layout + hand-rolled key handling, exercised via Textual's `run_test()`/`Pilot` harness) using Textual 8.2.8 on Python 3.11.

- **Multi-pane layout** — a lazygit-style 2x2 layout is straightforward with a `Grid` container (`grid-size: 2 2`, `grid-gutter`), one bordered `Static`-based pane per quadrant. No issues here; this generalises to the four panes named in the implementation plan.
- **Key chords** — Textual's `BINDINGS` system is built for single keypresses and simultaneous modifiers (e.g. `ctrl+a`), not sequential chords. There is no built-in "leader key" primitive, so any multi-key sequence has to be hand-rolled state tracked through an `on_key` override.
  - A comma-separated key string such as `"ctrl+j,space,x"` looks like it might specify a sequence, but it doesn't: checked against Textual's source (`Binding.make_bindings`) and confirmed empirically, it expands into independent alternative single-key bindings for the *same* action (`ctrl+j` OR `space` OR `x`, any one of them fires it), not a rigid press-in-order sequence. Not usable for bank-then-pad chords.

Two sequencing approaches were spiked, both fully working (7 tests, all passing on the final version):

1. **Raw timed chord** — bank letter (A-H) sets a `pending_bank` and starts a `set_timer` timeout; a pad digit (1-6) before the timeout completes the assignment; any other key, or the timeout firing, cancels. Fast once memorised, but relies on a clock the user can't see, and a slow second keypress silently cancels the whole chord.
2. **Explicit submenu** — `a` (assign) moves into an `AWAITING_BANK` state and the status pane lists the valid bank letters; picking one moves into `AWAITING_PAD` and lists the valid pad digits; `Escape` cancels at either step. No timer, no ambiguity about what's expected next, and each step is self-documenting on screen. This is the preferred approach — recorded in `spike.py`/`test_spike.py`.

- **Verdict** — Textual is suitable for both the layout and either input style. Proceed with it as the TUI library, using the explicit submenu state machine (`Mode.IDLE` / `AWAITING_BANK` / `AWAITING_PAD`) as the pattern to carry into the real assignment engine/TUI wiring (phase 4 of the implementation plan).

## Alternative keyboard interaction styles, closer to Textual's own idioms

The submenu above is still a hand-rolled `on_key` state machine sitting outside Textual's normal input model. Some alternatives that lean more on what Textual already provides:

- **Grid-cursor navigation** — make the assignment pane a focusable grid (e.g. a `DataTable` with 8 rows x 6 columns, or a custom widget), move a highlighted cell with the arrow keys, and press `Enter`/`Space` to assign the currently-browsed sample to that cell. This needs no custom chord or menu grammar at all — arrow-key/cell-cursor movement and selection are native `DataTable` behaviour. Best affordance for discoverability (you can see the whole bank/pad grid and where the cursor is at all times); slower than a memorised chord for someone who already knows they want `E4`.
- **Screen-stack modals** — instead of updating the status pane in place, push a `ModalScreen` containing an `OptionList` for bank choice, then another for pad choice, using Textual's normal screen stack (`push_screen`/`pop_screen`) rather than manual mode tracking. Behaves like the submenu above but gets Textual's built-in list widget, keyboard navigation, and dismiss-on-`Escape` for free, at the cost of a modal appearing over the layout rather than a quieter status-pane prompt.
- **Command palette** — Textual ships a command palette (default `ctrl+p`) that fuzzy-matches registered commands. Assignment actions (`Assign to Bank A Pad 1`, etc.) could be exposed as a `Provider`. Fits entirely within Textual's existing mechanism with no custom widget code, but 48 bank/pad combinations as flat commands is a lot to search through, so it likely wants to stay a secondary/power-user path rather than the primary assignment flow.
- **Direct per-bank `BINDINGS`** — bind each bank letter as a normal single-key `Binding` (`("a", "select_bank_a", "Bank A")`, etc.) so the `Footer` widget automatically shows the available keys, then handle the pad step with a lighter follow-up prompt. Splits the difference: the first step is idiomatic Textual with automatic footer hints; only the second step needs bespoke handling.

None of these were spiked in code — worth a quick trial of the grid-cursor and screen-stack options if the submenu approach doesn't feel right once it's wired to real data, since both are closer to "what Textual gives you for free" than either chord variant.

## Settled design: hybrid grid + submenu

Decided against grid-cursor navigation as the way to *create* an assignment — having to move the cursor onto a pad before assigning to it is an unwanted extra step. Settled on a hybrid, spiked and passing (7 tests):

- **Assignment grid pane** — a cursor-navigable `DataTable` (one row per bank, one column per pad, row label showing the bank letter so the pad columns line up 1:1 with `PADS` with no index offset), showing the currently assigned sample name or `-` per cell. Arrow keys move the cursor using `DataTable`'s native navigation — no custom code needed for that part. When this pane is focused and no chord is pending, single keys act on the pad under the cursor:
  - `d` — delete/clear the assignment on that pad
  - `p` — preview the sample assigned to that pad
  - `i` — show file info for the sample assigned to that pad
- **Creating an assignment** — still the explicit submenu, triggered from the file browser pane (`a` on a highlighted sample → pick bank → pick pad), independent of wherever the grid cursor happens to be. The completed assignment writes directly into the grid via `pad_column_coordinate(bank, pad)` — the target cell updates without the cursor ever moving there.
- **Clearing/inspecting an assignment** — grid-cursor-based, as above, since you're already looking at the pad you want to act on.

### Gotcha found while spiking this: bound keys still bubble

Went in assuming a widget's own key binding (e.g. `ListView`'s built-in `down` binding for moving the highlight) would consume that keypress before it could reach an ancestor's `on_key`. That's wrong: Textual's action-binding dispatch and raw `Key`-message bubbling are separate mechanisms, and firing a bound action does **not** automatically stop the event. So with the file browser focused and a bank/pad chord pending, pressing `down` **both** moves the file browser's highlighted item **and** bubbles up to the app's chord handler, which sees an unrecognised key and cancels the pending assignment. Confirmed with a test (`test_arrow_key_during_pending_chord_both_moves_list_and_cancels`) — the list selection changes and the chord cancels, in the same keypress.

This is a real constraint for the real implementation, not just the spike: any App-level modal/chord state sitting on top of focusable, self-navigating widgets (`DataTable`, `ListView`, etc.) needs to either explicitly re-stop/swallow bubbled keys while a chord is pending, or the widgets need to be defocused/disabled for the duration of the chord, otherwise navigation and modal input silently interact.

## Vim-style navigation and numbered pane jumps

Both spiked and passing (11 tests total):

- **Vim keys (`h`/`j`/`k`/`l`)** — added as extra `BINDINGS` entries on the `AssignmentGrid`/`FileBrowser` subclasses pointing at the same `cursor_left`/`cursor_right`/`cursor_up`/`cursor_down` action names `DataTable`/`ListView` already use for the arrow keys. Textual merges a subclass's `BINDINGS` with every base class's `BINDINGS` up the MRO rather than replacing them (confirmed by inspecting `DataTable.BINDINGS` after subclassing with an extra entry — the arrow-key bindings were still present alongside the new one), so arrow keys and vim keys both work with no duplicated logic. `ListView` only scrolls vertically, so it only gets `j`/`k`.
- **Numbered pane jumps (`1`-`4`)** — handled as a fourth branch in the existing `on_key` dispatcher, checked once the chord-priority branch has ruled out a pending assignment, and before the focused-widget-specific handling. Working mapping in the spike: `1` file browser, `2` assignment grid, `3` configuration list, `4` status/log — **the plan only specified `1`→browser and `2`→grid; `3`/`4` are my extrapolation for the remaining two panes and worth confirming**. `ConfigList`/`StatusLog` needed `can_focus=True` added since plain `Static` isn't focusable by default.
- Confirmed digits don't get stolen by the pane-jump handler while a pad chord is in progress — the mode-check branch still runs first, so `4` mid-chord is "pad 4", not "jump to the status pane".

## Colour scheme taken from the terminal's own configuration

Yes, and confirmed by inspecting the actual bytes Textual emits, not just the docs. Textual has built-in `ansi-dark`/`ansi-light` themes (`textual/theme.py`) whose colours are all named ANSI slots (`ansi_default`, `ansi_black`, `ansi_blue`, …) rather than fixed hex. Setting `App.theme = "ansi-dark"` sets `native_ansi_color` from the theme's `ansi=True` flag, which disables Textual's `ANSIToTruecolor` filter — so, unlike the normal named themes (`textual-dark`, `nord`, `catppuccin-mocha`, etc., which always emit `38;2;r;g;b` truecolor escapes regardless of terminal settings), an ansi theme emits plain SGR codes:

- `ansi_default` (used for the base text/background) → `\x1b[39;49m` — "reset to whatever the terminal's own default foreground/background is"
- `ansi_blue` (used for `primary`/accents in the ansi themes) → `\x1b[34m` — a base palette-index code, so the actual hue shown is whichever colour the terminal emulator has configured for that slot (this is exactly the per-scheme customisation most terminal emulators — Alacritty, Ghostty, iTerm2, Kitty, etc. — expose)

Confirmed with a throwaway Rich `Style` render comparing all three cases (`ansi_default`, `ansi_blue`, and a fixed truecolor hex) side by side — the first two produce short palette-index escapes, the truecolor one produces a fixed RGB escape unrelated to any terminal setting.

Caveats before wiring this into the real app:
- Only the 16 basic ANSI slots are available this way — "highlight colour" means one of `ansi_black`..`ansi_white`/bright variants, not an arbitrary RGB pulled from the terminal.
- It only applies to colours actually declared as `ansi_*` (or left as theme variables that resolve to them). Our own `app.py` CSS currently hardcodes `border: round white;` — a literal colour name, not `ansi_default`/a theme variable — so it would need changing to actually follow the terminal's scheme once an ansi theme is selected; anything hardcoded bypasses this regardless of which theme is active.

Applied to `P6ToolApp`: starts on `theme = "ansi-dark"`, `ctrl+t` toggles to `"ansi-light"` and back (`action_toggle_theme`), and the file browser's border now reads `$foreground` instead of the hardcoded `white` it had before. Covered by `tests/test_theme.py` (2 tests: starts on `ansi-dark` with `native_ansi_color` true, `ctrl+t` toggles both ways).

**Toggle removed on request.** `ctrl+t`/`action_toggle_theme` are gone - the app is fixed on `ansi-dark` (renamed constant `THEME`, was `ANSI_THEMES`). The terminal's own light/dark setting already governs how an ansi theme actually renders (that's the whole point of the section above), so a separate in-app toggle on top of that was redundant, not a real second axis of control. `test_theme.py` now only covers the fixed starting theme.
