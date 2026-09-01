# Aim

i would like to add support for another device, the elektron digitakt 2. This device does not allow usb access to storage so we will need to find another means. I have included the user guide in the references folder.

# tasks

- [] investigate options for transfering files or packs to the digitakt, what other tools already exist and what can we learn from them.

# Review notes

Full findings written up in `docs/reference/digitakt-2-transfer-notes.md`
(mirrors `circuit-tracks-transfer-notes.md`'s role for the CT work).
Read the manual (`docs/reference/Digitakt-2-User-Manual_ENG_OS1.15A_250708.pdf`)
directly plus researched community tooling. Headline points:

- **Worse than the CT case in one respect**: the Digitakt II has no SD card
  slot at all - only USB and DIN MIDI. There's no removable-media fallback
  to fall back on the way the CT investigation eventually found one; every
  transfer route is USB MIDI SysEx.
- **The official route (Elektron Transfer, a free desktop app) is GUI-only**
  - no CLI/API, protocol undocumented by Elektron - not automatable.
- **The manual claims standard MIDI Sample Dump Standard (SDS) support for
  samples**, which would have been the best-case outcome (a real published
  standard, not reverse-engineered). This claim is directly contradicted by
  the most credible independent source found (`elk-herd`'s author) and
  structurally corroborated by `elektroid` keeping its Elektron protocol
  support in a separate module from its generic SDS one - treat the manual
  text as inherited boilerplate, not a verified capability, until tested
  against real hardware.
- **Stronger prior art than the CT case**: `dagargo/elektroid` (GPLv3, C) is
  a mature, actively-maintained open-source tool with explicit Digitakt II
  device support and a real sample-upload/download implementation to learn
  from - a better starting reference than anything available for CT was.
  Its licence (GPLv3, vs. CT's MIT `circuit-tracks-tools`) is worth
  resolving before any actual porting, given shmample currently has no
  declared licence of its own.
- **Format target differs from CT**: Digitakt II wants 16-bit/48 kHz, mono
  *or* stereo - not CT's mono-only constraint. The existing
  `audio_convert.py`/`SampleFormat` machinery built for CT should cover this
  with a new format value, no rework needed there.
- No implementation work has started; this task was investigation-only, per
  the aim.

# Next step - live capture experiment

Stuart doesn't own a Digitakt II himself, but has someone who does and can
test on macOS. Rather than have them fight `elektroid`'s unresolved macOS
build issue (dagargo/elektroid#108) to test the community protocol
directly, the chosen experiment is to capture real traffic straight from
Elektron's own Transfer app instead: `tools/digitakt2_midi_sniff.py` is a
transparent MIDI proxy (`python-rtmidi`) that sits between Transfer and the
real hardware, relays everything so Transfer/device behave normally, and
logs every SysEx message in both directions. Instructions for the tester
are in `tools/digitakt2_midi_sniff.md`. Once a capture comes back, the next
step is decoding it against `docs/reference/digitakt-2-transfer-notes.md`'s
open questions (is it really proprietary Elektron SysEx or standard SDS,
what's the directory-listing/upload framing) before any implementation
work starts.
