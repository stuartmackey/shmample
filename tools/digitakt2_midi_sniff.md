# Digitakt II MIDI sniff — instructions

Goal: capture the real SysEx traffic Elektron Transfer uses to move samples
and projects to/from a Digitakt II, so shmample can eventually implement
this itself. Background: `docs/reference/digitakt-2-transfer-notes.md`.

We're going this route rather than trying the open-source `elektroid`
project's own implementation because its macOS build has an unresolved
linker issue upstream (dagargo/elektroid#108) - capturing straight from
Elektron's own app avoids relying on getting someone else's C build working
first, and gives us the authoritative protocol rather than a third party's
possibly-incomplete reimplementation.

## Setup

1. Install [Elektron Transfer](https://www.elektron.se/support) if not
   already installed.
2. `pip install python-rtmidi` (installs a prebuilt wheel on macOS, no
   build tools needed).
3. Grab `digitakt2_midi_sniff.py`, `digitakt2_test_tone_mono.wav`, and
   `digitakt2_test_tone_stereo.wav` from this folder.

   The two WAV files are generated test tones (`generate_digitakt2_test_samples.py`
   is the generator, if you ever want to regenerate or tweak them), already
   16-bit/48kHz - the format the manual documents as Digitakt II's native
   format - so what Transfer does with them isn't confused by its own
   format-conversion step. `_mono.wav` is a 2-second 440Hz tone; `_stereo.wav`
   is 440Hz on the left channel and 880Hz on the right, so it's audibly
   obvious if channels get swapped or collapsed anywhere in the round trip.
   2 seconds is deliberately short (~190-380KB) to keep the capture small
   while still spanning several SysEx data blocks, based on how chunked the
   equivalent Circuit Tracks protocol turned out to be.

## Running it

1. Connect the Digitakt II via USB.
2. Run the script:

   ```
   python3 digitakt2_midi_sniff.py
   ```

   It should auto-detect the Digitakt's MIDI ports and print something
   like:

   ```
   Real device input:  Digitakt II
   Real device output: Digitakt II

   Proxy ports open as "Digitakt II Proxy".
   In Elektron Transfer's CONNECTIONS page, connect to those instead of the real Digitakt II.
   Use Transfer normally. Press Ctrl+C here when done.
   ```

   If it can't find the device automatically, run `python3
   digitakt2_midi_sniff.py --list` to see the exact port names, then pass
   `--device-in "<name>" --device-out "<name>"`.

3. Open Elektron Transfer. On its CONNECTIONS page, connect to **"Digitakt
   II Proxy"** for both MIDI in and out - not the real "Digitakt II" entry.
   The script sits transparently in between, so Transfer and the device
   should behave exactly as normal.

4. Use Transfer as you normally would. Ideally, in this order, so we can
   see each operation's traffic separately (leave a pause between each so
   it's easy to tell them apart in the log):
   - Open the EXPLORE page and just browse the +Drive sample directory for
     a few seconds (directory listing traffic).
   - Drag `digitakt2_test_tone_mono.wav` from "My Computer" to the device.
   - Drag that same sample back from the device to "My Computer" (under a
     different name, so we can tell the two transfers apart afterwards).
   - Repeat both of the above with `digitakt2_test_tone_stereo.wav` - the
     manual says Digitakt II accepts stereo samples, unlike the Circuit
     Tracks work this project's already done, and it'd be good to see
     whether the wire protocol treats stereo any differently.
   - If you're up for it: create a new destination directory on the device
     (Transfer's "create folder" action) - the manual describes this as
     part of the sample-upload flow and it'd be good to see it captured
     too.

5. When done, `Ctrl+C` the script. It'll have written a file named
   `digitakt2_sniff_<timestamp>.log` in whatever directory you ran it
   from - send that back. Since you'll have used the two known test files
   above, we won't need you to also send back the samples themselves.

## What we're hoping to learn

- Whether the traffic really is proprietary Elektron SysEx (matching
  `elektroid`'s `connectors/elektron.c`) or genuinely standard MIDI Sample
  Dump Standard, as the manual claims and the community disputes.
- The message framing/header format for directory listing and sample
  upload/download, so we can plan an implementation.
- Whether it behaves any differently over the proxy than it would direct
  (i.e. whether Transfer's SDS handshake or similar has timing sensitivity
  the relay might trip up) - if Transfer errors out or behaves oddly, that
  itself is useful information, not just a failure.
