# shmample

Browse, tag, and preview samples in the terminal.

## Setup

Requires Python 3.11+. With [mise](https://mise.jdx.dev/) installed:

```sh
mise run setup
```

This runs `uv sync --extra dev`, which creates `.venv` and installs both the app and its dev
dependencies (pytest, pytest-asyncio). Without mise, run that `uv` command directly.

## Running the automated tests

```sh
mise run test
```

or directly:

```sh
.venv/bin/python -m pytest
```

Don't `source .venv/bin/activate` - use `.venv/bin/python`/`.venv/bin/pytest` directly, so the
right interpreter is used without depending on shell state.

To run a single file or test:

```sh
.venv/bin/python -m pytest tests/test_file_browser.py
.venv/bin/python -m pytest tests/test_file_browser.py -k test_vim_keys_navigate
```

### What the tests exercise

This is a [Textual](https://textual.textualize.io/) app - most tests build a real `ShmampleApp`
(or a smaller `App` wrapping a single widget) and drive it with Textual's own test harness:

```python
async def test_something():
    app = ShmampleApp(samples_directories=[some_dir])
    async with app.run_test() as pilot:
        await pilot.press("j")
        ...
```

This runs entirely headless - no real terminal/tty needed, safe to run in CI or over SSH.

Autouse fixtures in `tests/conftest.py` redirect every persisted file (`settings.json`,
`configurations/`, and `shmample.db`, the sqlite store behind tagging and the preview cache) to a
per-test `tmp_path`, and stub out real subprocess calls for audio playback/device detection. Tests
never touch your real `~/.config/shmample`, spawn a real audio player, or require a P-6/Circuit
Tracks to actually be plugged in.

## Trying it out manually

```sh
mise run tool
```

or directly: `.venv/bin/shmample`, or `.venv/bin/shmample --samples-dir /path/to/samples` to add
a samples directory on the way in.

A quick manual smoke test, once it's running:

- `Shift+A` in the samples pane (`3`) to point it at a real folder of `.wav` files.
- `j`/`k`/`gg`/`G` (or arrow keys) to move around, `Enter`/`p` to preview a highlighted sample.
- `t` to auto-tag the highlighted file or folder, then check the tag pane (`4`) picks up the new
  counts, and the preview pane (`5`) shows the tags on its date/duration/size line.
- `1`-`6` jump focus between panes (Device, Configurations, Samples, Tags, Preview, Assignments).
- `n` in the configurations pane (`2`) to create a configuration, then `a` in the samples pane to
  assign a highlighted sample to a pad.

Automated tests are the source of truth for correctness - this is just enough to confirm a change
actually renders and responds as expected, which the test suite alone can't tell you.

## Project layout

- `src/shmample/` - application code; `widgets/` holds one file per pane/modal.
- `tests/` - one test file per widget/module, named to match.
- `docs/tasks/` - feature briefs and the decisions made while building them; `docs/reference/`
  has the device manuals (P-6, Circuit Tracks) referenced from the code.
