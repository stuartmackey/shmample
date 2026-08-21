# Brief

Carried over from the open question in `01-initial-description.md`/`02-implementation-plan.md`: find a way to preview a sample's audio, either an in-process cross-platform library or shelling out to the OS's default player.

# Spike: shelling out to the OS audio player

Verified for real on this machine (Linux, PipeWire + PulseAudio compatibility layer) rather than assumed:

- Generated a genuine WAV tone (stdlib `wave` module, no extra dependency, a 440Hz sine) and played it with `paplay tone.wav` directly in a shell. Ran for ~0.69s wall-clock against a 0.6s tone - consistent with real playback plus small process-startup overhead, not an instant no-op.
- Built a small Textual app (`preview_spike.py`) wrapping `asyncio.create_subprocess_exec("paplay", path)` in a `Previewer` class, started via `App.run_worker(..., exclusive=True, group="preview")`. Confirmed:
  - starting a second preview while a 3-second tone was ~0.4s into playing killed the first `paplay` process and started the second immediately - total elapsed was ~1.6s (0.4s + the second tone's 0.6s + overhead), not ~3.4s, proving the first one was actually interrupted, not just superseded while continuing in the background
  - `pgrep -a paplay` after the run showed nothing - no orphaned process left running
  - this needed an explicit `try/except CancelledError/finally: proc.kill()` around the `await proc.wait()` - cancelling the asyncio task alone does **not** kill the underlying OS process, it just stops awaiting it

`exclusive=True` workers are exactly the "starting a new preview should stop whatever's already playing" behaviour we want, and the kill logic above is what makes that actually work rather than leaving `paplay` processes piling up in the background.

**Cross-platform note**: `paplay` is Linux/PipeWire-Pulse-specific - not present on macOS or Windows. A real cross-platform version needs a per-platform dispatch: something like `paplay`/`pw-play`/`ffplay`/`mpv` (first found on `PATH`, via `shutil.which`) on Linux, `afplay` on macOS, and on Windows the stdlib `winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)` is actually a better fit than shelling out at all - it's already non-blocking and needs no subprocess or extra dependency. Only the Linux path above was actually verified; macOS/Windows are the standard documented approach for each OS but unverified here.

# Spike: `simpleaudio` (in-process library) for comparison

- `uv pip install simpleaudio` had to build from source on this machine (no prebuilt wheel for this Python/platform combination) - meaning it needs a C compiler and ALSA dev headers present to install at all. Worse cross-platform install story than "the OS already ships a way to play a WAV file", which every target OS does.
- Functionally it does work: `WaveObject.from_wave_file(path).play()` returns immediately (non-blocking) and a second clip played correctly after calling `.stop()` on the first.
- But `PlayObject.is_playing()` kept reporting `True` for at least 250ms after `.stop()` was called, in this environment - not confidence-inspiring for a status flag we'd want to rely on. The stop-then-replace behaviour worked in wall-clock terms regardless, but the flakiness of the status API is a mark against it.
- Integration-wise, its API is thread-blocking-callback style rather than asyncio-native, so it'd need `run_worker(thread=True)` in Textual rather than the clean `asyncio.create_subprocess_exec` + native `await` used above.

# Recommendation

Shell out, dispatched per platform, rather than an in-process library. It needs no extra dependency to install (every OS already ships a way to play a WAV file), integrates cleanly with Textual's `run_worker(exclusive=True)` for "new preview kills the old one", and was verified end-to-end on Linux. `simpleaudio` needed to compile from source here and showed a flaky status API - worse portability story and less trustworthy, for no real benefit since we don't need in-process mixing/effects, just "play this one file until stopped."

# Open items for implementation

- Player-selection order for Linux (`paplay` → `pw-play` → `ffplay` → `mpv`, first found) - not yet decided which order, or whether to just always try `paplay` first given it's already confirmed present and it's the lightest of the four for a plain WAV.
- Where the `Previewer`/kill-on-replace logic lives - presumably a small module the `FileBrowser`'s `p`/Enter preview hooks call into, replacing the `last_previewed`-only stub from `04-file-browser.md`.
- What happens if no player at all is found on `PATH` (e.g. a minimal Linux install with none of the four) - should probably surface a status message rather than silently do nothing.

# Spike: static waveform display (not live, a one-shot preview image)

Follow-up question: can we show a static waveform for the highlighted sample, rendered once rather than animated during playback.

Ran with this session's terminal context, which matters here: `TERM_PROGRAM=tmux`. tmux does not reliably pass through terminal graphics protocols (Kitty/Sixel/iTerm2 inline images), so any approach depending on one of those risks not rendering at all for a fairly common setup (tmux/screen, SSH sessions, some terminal+multiplexer combos) - text/ANSI-based plotting doesn't have that risk since it's just characters.

**Decoding**: stdlib `wave` + `array` is enough - no extra dependency needed, and it's already `.wav`-only per `04-file-browser.md`'s filter. Downsampled a synthesized decaying "snare-like" WAV (noise + tone under an exponential envelope, generated with only stdlib `wave`/`math`/`random`, so the test data itself has a known, verifiable shape) into peak-per-bucket amplitude values, one bucket per terminal column.

**Rendering, two options compared**:

1. **`plotext`/`textual-plotext`** (text/ANSI plotting, no image protocol) - installed cleanly, no compiled dependencies. Built a small Textual app (`waveform_spike.py`) that decodes the wav, computes per-column peak amplitude, and plots it mirrored above/below zero (`marker="braille"` for finer resolution than block characters) via `PlotextPlot`. Rendered via Textual's screenshot export, converted SVG→PNG (`rsvg-convert`) to actually look at it, not just check for absence of an exception: it's a clean, legible mirrored amplitude envelope that visibly matches the synthesized decay shape. This works purely as text/ANSI, so it renders the same regardless of tmux/SSH/terminal graphics support.
2. **`textual-image`** (real image, via a terminal graphics protocol with a half-block ANSI fallback) - installed cleanly but pulls in Pillow (~6.6MB) as a dependency, and doesn't do any plotting itself - we'd still need to draw the waveform ourselves (PIL `ImageDraw` or matplotlib) before handing a rendered image to it. Heavier dependency chain for no real benefit here: we don't need photographic image fidelity, just a bar/line shape, and its nicest rendering path (an actual graphics protocol) is exactly what's unreliable in this session's terminal context.

**Recommendation**: `plotext`/`textual-plotext` for the same reason as the playback recommendation above - lighter, no compiled/binary dependency, and doesn't gamble on terminal graphics protocol support.

**Not yet decided**: whether `p`/Enter should show the waveform, play the audio, or both at once.

## Legibility at small pane sizes

Layout decision (see `04-file-browser.md`): the waveform goes in a small info pane at the bottom of the file browser's own column, about 1/5 of its height - not a pane of its own. Checked whether the plot is still legible that small, since plotext's default decorated style (title, axis labels, frame, x/y ticks) eats most of the space in a short pane and leaves too little vertical resolution to see any shape:

- At 39 columns x 8 rows (roughly 1/5 of a 40-row-tall file browser at 1/3 terminal width) with the default decorated style, the plot was barely readable - axis chrome consumed most of the 8 rows, leaving only 2-3 rows of actual waveform.
- Stripped it down with `plt.frame(False)`, `plt.xticks([])`, `plt.yticks([])` (no title either) - same data, same size, and the decaying envelope shape is now clearly visible using the full 8 rows. Confirmed by rendering and looking at both versions side by side, not just assuming the API calls would help.

For a pane this size, skip plotext's axis chrome entirely - it isn't a real chart the user needs to read values off, just a shape.

## Implemented

`load_waveform_peaks` (`src/p6_tool/waveform.py`) decodes a wav with stdlib `wave`/`array` into one peak-per-column, returning `[]` for anything that fails to decode (missing, corrupt, empty, unsupported sample width) rather than raising - deliberately broad exception handling, since a bad file on disk should degrade to "no waveform", not crash the app (this was caught by a test: a zero-byte stub `.wav` raised a bare `EOFError` from inside `wave.py`, not caught by the narrower `except (wave.Error, OSError)` first tried). `PreviewInfo` (`src/p6_tool/widgets/preview_info.py`) renders it borderless via `textual-plotext`, alongside the file's name and `st_ctime` as a proxy for creation date - Linux has no stdlib-exposed true birth time (`os.stat().st_birthtime` doesn't exist here), so this is "last metadata change", which in practice matches "when the file was added" for a sample that's copied once and never edited, but isn't a strict guarantee.

**Bug found after "implemented"**: the pane wasn't showing waveforms at all for real sample files. The first version only handled 16-bit PCM - anything else (returned `[]`, the "can't decode" path) rather than an error, so it looked like nothing was wrong until actually checked against real files. 24-bit is a common bit depth for sample libraries and has no native `array` module typecode (it's 3 bytes/sample, not a C integer size), so it needs its own byte-level decode rather than `array.frombytes()`. Fixed to handle 8/16/24/32-bit integer PCM and multi-channel files (first channel only) - covered by dedicated tests per bit depth plus a stereo test. **Still not handled**: 32-bit *float* PCM - stdlib `wave` doesn't expose the WAV format tag needed to distinguish it from 32-bit int, so a float32 file would decode as int and look wrong (not crash, per the broad exception handling above, but silently incorrect rather than blank). Worth checking for if a real file still doesn't show a sensible waveform after this fix.

## Playback implemented

`src/p6_tool/audio.py` carries the spike's design forward largely as designed: `build_play_command(path)` is the pure per-platform player selection (`paplay`→`pw-play`→`ffplay`→`mpv` on Linux, `afplay` on macOS, first found via `shutil.which`; Windows doesn't use it at all - `Previewer` calls stdlib `winsound.PlaySound` directly there, no subprocess involved), and `Previewer` owns the kill-on-replace process lifecycle. `FileBrowser` owns one `Previewer` and starts a preview via `self.run_worker(self._play(path), exclusive=True, group="preview")` from both `p` and the native `FileSelected` (Enter) event - `exclusive=True` is what makes a new preview supersede an in-progress one rather than queuing.

**Real bug caught by a test while wiring this up, not present in the original spike**: a race condition in `Previewer.play()`/`stop()` - both referenced the shared `self._proc` attribute in their cleanup (`finally`/`stop()`) rather than a locally-captured reference. If a second `play()` call arrived while the first was still awaiting its process, the first call's cleanup could end up killing the *second* call's process instead of its own, since by the time its `finally` block ran, `self._proc` had already been reassigned. Caught directly by `test_starting_a_new_preview_kills_the_one_in_progress` in `tests/test_audio.py` (using a controllable fake process, not real audio) - it failed until both methods were changed to capture `proc = self._proc` (or the freshly-created process) locally and operate on that, not the mutable shared attribute.

**Second bug caught while wiring, unrelated to audio itself**: when the configured samples directory doesn't exist, `DirectoryTree` treats its own root node as a leaf ("file") - `_safe_is_dir` on a missing path is `False` - and fires `FileSelected` for that root automatically on mount. Without a guard, `_start_preview` would try to "preview" a nonexistent path. Fixed with a plain `path.is_file()` check at the top of `_start_preview`, covered by a dedicated regression test.

**Testing approach**: an autouse fixture in `tests/conftest.py` replaces `asyncio.create_subprocess_exec` with an instantly-finished fake for every test in the suite, since `p`/Enter on a file now goes through the real preview wiring everywhere - without it, the whole test suite would spawn real player processes (and make real sound) on every run. `tests/test_audio.py` has its own more controllable fake process for the tests that specifically need to observe kill-on-replace timing. One real end-to-end check was done outside the automated suite (a synthesized 660Hz tone played via the actual `FileBrowser`→`Previewer`→`paplay` pipeline, not mocked) - confirmed audible.

## Waveform background didn't match the terminal

Reported: the waveform plot's background was always a solid dark colour, unlike every other widget - the rest of the UI blends with the terminal (via the ansi themes + `Widget`'s own `background: transparent` default, per `03-skeleton-tui.md`), but `PlotextPlot` doesn't get that for free.

Cause: `textual-plotext`'s default `theme="auto"` derives a Plotext theme from `$surface`/`$foreground`, but that resolution bakes them into a fixed RGB fill (`Color.parse(...).rgb`) - under the ansi themes those variables are symbolic (`ansi_default`), and the fixed RGB Plotext falls back to reads as plain black rather than "whatever the terminal's default actually is". Confirmed directly: rendering the same plot's `render()` output showed every span had an explicit `bgcolor` set under `"auto"`, and none under Plotext's built-in `"clear"` theme (which emits no background colour codes at all) - checked the actual ANSI output, not just the theme name.

Fixed by setting `plot.theme = "clear"` on the `PlotextPlot` in `PreviewInfo.compose()` - with no background codes of its own, the widget's real transparent background (and the terminal behind it) shows through, same as everywhere else. 1 more test confirming `plot.theme == "clear"`.

## Feature: file size added to the status line

Requested once `08-assignment-grid.md`'s pad-size display and `09-save-assignments.md`'s device-capacity checks made file size a running concern elsewhere in the app - the preview pane showed name/date/duration but never how big the file actually was.

Added to `#preview-date` (the name/created/duration line), not `#preview-format` (sample rate/bit depth/channels) - size is a filesystem fact like the creation date already shown there, not an audio-encoding one. `device.human_bytes()` reused rather than reimplemented, same formatter `08`/`09`'s pad and configuration-list sizes already use, so all three places in the app read consistently. `PreviewInfo.show()` now does a single `path.stat()` call and reads both `st_ctime` and `st_size` off it, rather than the two separate stats it effectively did before (one implicit inside the old `path.stat().st_ctime` expression, plus what would have been a second for size).

1 test extended (not added) - `test_highlighting_a_file_shows_its_name_date_duration_and_size` (renamed from `..._date_and_duration`) now also asserts the file's actual size (via `human_bytes(path.stat().st_size)`, not a hardcoded string, so it can't drift from wave's own header size or `human_bytes`'s rounding) appears in the line.
