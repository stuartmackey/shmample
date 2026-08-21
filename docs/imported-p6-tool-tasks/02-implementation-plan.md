# Implementation plan

Based on [01-initial-description.md](01-initial-description.md). Covers import (samples onto the P6) only. Export is out of scope until it's defined.

# Tech stack

- Language: Python
- TUI library: not yet chosen. Needs to support a lazygit/lazydocker-style multi-pane layout with keyboard-chord input. Textual is the obvious first candidate to evaluate; confirm it can handle key-chord sequences (A then 1) before committing.
- Audio playback: open question (see brief). Needs a spike to find a library that works cross-platform, or fall back to shelling out to the OS default player.

# Data model

- `Configuration`
  - `name`
  - `description`
  - `created_at`
  - `modified_at`: updated on every save (see `06-configuration-list.md`)
  - `assignments`: mapping of `(bank, pad)` to an original sample filepath
    - bank: `A`-`H`
    - pad: `1`-`6`
    - one sample per pad, assigning a new sample to an occupied pad replaces the existing assignment
- Stored as JSON files under `~/.config/p6-tool/configurations`
- A configuration is either **saved** (persisted, no device interaction) or **committed** (samples actually transferred). Committing requires the assignments to be settled and all referenced sample files to still exist.
- `Settings` — app-wide, not tied to any one configuration
  - `samples_directory`: where the file browser starts
  - stored as a single JSON file, `~/.config/p6-tool/settings.json`, distinct from the `configurations/` directory above
  - set via a `--samples-dir PATH` CLI flag on the tool entrypoint, which both uses that path for the current run and persists it to `settings.json` for next time; no in-TUI settings screen yet

# Modules

1. **Config store** — load/save `Configuration` objects as JSON, list existing configurations. Also owns `Settings` load/save (`settings.json`) and the `--samples-dir` flag handling, since it's the same "small JSON file under `~/.config/p6-tool`" concern.
2. **Sample browser** — scan a configured samples directory, list files, trigger preview playback.
3. **Assignment engine** — in-memory bank/pad grid for the configuration being edited, applies key-chord input (bank letter, then pad number) to set an assignment.
4. **Device transfer** — given a mounted P6 path:
   - locate `IMPORT/BANK_<X>/PAD_<Y>/` for each assignment
   - validate all assigned sample files still exist before starting; abort commit and flag to the user if any are missing (per brief, commit does not run)
   - copy each sample into its target pad folder as-is (no resampling/conversion yet)
   - leave `info.txt` untouched, it's device-generated
   - after copying, prompt the user to confirm the import on the device itself before it's safe to unmount
5. **TUI** — panes, not a 2x2 grid but a lazygit-style layout: configuration list, file browser, and its preview info all stack in one column (see `04-file-browser.md`/`06-configuration-list.md`), with the pad-assignment grid occupying the rest:
   - configuration list (previous configurations) - stacked above the file browser
   - file browser with preview - as implemented
   - selected configuration's sample/pad assignments - the remaining pane
   - key-chord input handling and status/feedback for assignments and commit results

# Open questions carried over from the brief

- Can the sample rate/format sent to the device be controlled, or is as-is copying the only option for now?
- Which audio playback approach to use (in-tool vs OS handoff)?
- How is the P6 mount path found: user-configured path, or auto-detected by scanning mounted volumes for the `IMPORT`/`info.txt` signature?

# Suggested phasing

1. Data model + config store, no UI, testable via unit tests
2. TUI skeleton with the four panes wired to static/sample data
3. File browser + audio preview spike
4. Key-chord assignment editing, save vs commit distinction
5. Device transfer: validation, copy, device-confirmation prompt
6. Export (once defined separately)
