# Elektron Digitakt II — Content Transfer Reference

Research notes on how projects, presets, and samples get on and off a
Digitakt II. Compiled from Elektron's own documentation (`Digitakt-2-User-
Manual_ENG_OS1.15A_250708.pdf`, in this folder) plus community
reverse-engineering projects. Intended as reference material for another AI
coding agent scoping Digitakt II support in shmample - mirrors
`circuit-tracks-transfer-notes.md`'s role for the Circuit Tracks work.

---

## 1. No mass storage, and no SD card at all

The rear panel (manual §3.2) has exactly: power, DC in, USB, MIDI THRU/SYNC
B, MIDI OUT/SYNC A, MIDI IN, audio in/out, headphones. **There is no SD/
microSD card slot anywhere on the device** - unlike the Circuit Tracks,
there isn't even a removable-media fallback to investigate. Every path onto
the device goes over the single USB port (or the DIN MIDI ports), full stop.

Internal storage is the **+Drive**: 20 GB non-volatile flash, holding up to
128 projects, 1024 kits, 2048 presets (256 per bank, banks A-H), and up to
1016 sample slots (manual §5.1, §9.1). It is not exposed as a filesystem to
a host computer in any mode the manual documents.

---

## 2. USB has three distinct roles - only one is close to file transfer

- **Class-compliant USB audio/MIDI streaming** (manual §6.7): plug-and-play,
  no drivers, streams audio and MIDI to/from a computer/phone/tablet. This
  is for live audio routing (e.g. recording the Digitakt II into a DAW over
  USB), not file transfer.
- **Overbridge** (§6.6): tight DAW integration, presents the device as a
  plug-in window with full parameter control/automation and total recall.
  Also not a file-transfer mechanism.
- **USB MIDI** carrying either (a) Elektron's own proprietary SysEx-based
  file protocol (what Elektron Transfer speaks) or (b) plain MIDI CC/NRPN
  for real-time control. This is the only category relevant to "send a pack
  of samples to the device."

---

## 3. The official route: Elektron Transfer

A free desktop app (Windows/macOS) from elektron.se, described in manual
§6.8 and §13.6.7-13.6.9:

1. Connect via USB, open Transfer, connect to the device on its CONNECTIONS
   page.
2. EXPLORE tab shows both "My Computer" and the device's own +Drive as
   browsable trees.
3. Drag and drop files/folders either direction.
4. **Transfer automatically converts every audio file to 16-bit/48 kHz, the
   Digitakt II's native format - both mono and stereo are supported** (§13.6.7).
   This is a materially different constraint from the Circuit Tracks work
   (`circuit-tracks-transfer-notes.md` round 6): CT requires mono only, DT2
   accepts either.
5. New destination directories on the +Drive can be created directly from
   Transfer (§13.6.8).

Transfer is GUI-only - there's no documented CLI, API, or scriptable
interface, and Elektron hasn't published the protocol it speaks over the
wire. It's a fine tool for a human to use by hand, but not something
shmample can shell out to or automate against.

---

## 4. The manual's SDS claim - contradicted by the most credible community source

Manual §13.6.8 states plainly: *"The Digitakt II still supports receiving
of samples via MIDI Sample Dump Standard (SDS) and Extended SDS. You need
to enable SDS Handshake in order to secure the transmission over fast
interfaces like USB MIDI. You also have to enable the transmission of the
Extended SDS header if you want the sample name to be sent."* SDS is a
genuine, decades-old, publicly documented MIDI Manufacturers Association
standard (not Elektron-proprietary) - if true, this would be by far the
simplest, best-documented transfer path available for any device in this
project, P-6 included.

**This claim is directly disputed by `mzero`, the author of `elk-herd`**
(see §5) and one of the most active Elektron reverse-engineers in the
community, in an Elektronauts thread
(elektronauts.com/t/transferring-syx-files/117695/21): *"SDS is a SysEx
type that is supported by multiple synths… but not Digitakt."*

This is corroborated structurally by `elektroid` (§5): its Elektron
protocol support lives in a dedicated `connectors/elektron.c`/`.h` module,
kept entirely separate from the project's own generic `connectors/sds.c`/
`.h` implementation used for other (non-Elektron) devices - i.e. the most
mature open-source reference implementation for Digitakt file transfer
does **not** use its own SDS code path to talk to it.

**Read the manual text as boilerplate inherited from Elektron's shared
documentation template (the same paragraph shape likely appears across
several Elektron products' manuals) rather than a verified Digitakt II
capability.** Worth confirming directly against real hardware (enable SDS
Handshake, try a small sample dump from any generic SDS sender) before
relying on it for anything - this is exactly the kind of documentation/
reality gap that the CT investigation (`circuit-tracks-transfer-notes.md`
round 4) also ran into.

---

## 5. Settings-menu SysEx Dump - explicitly excludes samples

Manual §14.5 (SYSEX DUMP) sends/receives **project, pattern, and preset**
data over MIDI OUT or USB. The manual is explicit: *"Please note that Sysex
dump only sends and receives project, pattern and preset data. It does NOT
send or receive the presets['] samples."* Not a route to pack transfer on
its own - useful only for backing up/restoring non-sample project state.

---

## 6. Existing community tooling - stronger prior art here than for CT

Unlike the Circuit Tracks (where `namirsab/circuit-tracks-tools` was the
only real reference implementation, and even it had no working sample-write
path), Digitakt file transfer has multiple independent, mature, actively
maintained open-source projects to learn from:

### `elektroid` (dagargo/elektroid)

- **GPLv3, written in C, GTK GUI + CLI**, actively maintained.
- Explicit Digitakt II support: `connectors/elektron.h` defines
  `ELEKTRON_DIGITAKT_II_ID 42` (and `ELEKTRON_DIGITAKT_ID 12` for the
  original), alongside Analog Four/Heat/Rytm, Digitone, and others.
- Dedicated `connectors/elektron.c`/`.h` module implements the real
  protocol: `elektron_upload_sample_part()`, `elektron_download_sample_part()`,
  `elektron_get_sample_path_from_hash_size()`, `elektron_ping()`, plus a
  filesystem-type enum covering samples, raw presets, project/sound/preset
  data, Digitakt RAM, and per-track/per-loop views
  (`FS_SAMPLES`, `FS_DATA_SAMPLES`, `FS_DIGITAKT_RAM`,
  `FS_DIGITAKT_TRACK`, `FS_DIGITAKT_TRACK_LOOP`, etc).
- This is the strongest available reference for what the real wire protocol
  looks like - the natural next research step if/when this task moves from
  investigation to implementation.
- **Licence note**: GPLv3 is copyleft. Porting/adapting `elektron.c` code
  directly (as opposed to writing an independent implementation informed by
  reading it) would put a licensing obligation on whatever consumes it.
  shmample currently has **no declared licence at all** (no `LICENSE` file,
  nothing in `pyproject.toml`) - worth resolving that question before any
  actual porting happens, unlike the CT case where `circuit-tracks-tools`
  being MIT made "port the pieces" a licence-free decision.

### `elk-herd` (mzero)

- Unofficial Elektron device manager: explicitly supports Digitakt,
  Digitakt II, Analog Rytm (mk1/mk2), and Model:Samples - manages +Drive
  samples, sample pool, sound pool, and patterns.
- Runs as a **WebMIDI browser app** (Chrome-family only; no iOS), not a
  desktop binary.
- Open source, but **the repository has migrated off GitHub**; the
  GitHub-side stub (github.com/mzero/elk-herd, 67 stars, Elm) now just
  points at a personal code-hosting site with wording that discourages
  automated/AI access to the new location. Respect that - this doc
  deliberately does not chase the redirect. If a future task wants to study
  elk-herd's protocol handling in source, that means a human following the
  link by hand, not an agent fetching it.
- Author's own words (§4 above) are still directly useful even without
  reading the source: confirms Digitakt's real protocol is Elektron-
  proprietary, not standard SDS.

### `feamster/digitakt-midi-mcp`

- MIT-licensed Python MCP server for **live control only** - note
  triggering, CC/NRPN parameter control, transport, MIDI clock.
- **Explicitly does not implement sample or project transfer**, and states
  outright that "Elektron hasn't published the detailed protocol
  specification" for pattern/project SysEx.
- Not useful as a transfer-protocol reference, but corroborates that no
  official spec exists and that reverse-engineering (elektroid/elk-herd) is
  the only route to real protocol knowledge.

---

## 7. What this means for shmample specifically

- **No filesystem shortcut exists at all** - not even the "worked
  eventually, once we fixed the card reader" fallback that saved the CT
  effort (`04-export-to-ct.md` round 5). Every route is USB MIDI SysEx.
- **No dependency exists yet** for this in `pyproject.toml` (only
  `textual`/`textual-plotext`/`soundfile`/`soxr`). A MIDI transport
  (`mido` + `python-rtmidi`, as already flagged for the CT SysEx path)
  would be needed regardless of which protocol approach gets chosen.
- **Sample format target differs from both existing devices**: Digitakt II
  is 16-bit/48 kHz, mono *or* stereo (manual §13.6.7) - not the CT's
  mono-only 48 kHz requirement. shmample's existing `audio_convert.py`
  (`SampleFormat`, built for the CT work) is already parameterised by
  rate/channels/subtype, so a Digitakt-specific `SampleFormat` should slot
  in without rework of that module - only the device-specific send path is
  new work.
- **The realistic implementation path, if this is picked up**, is porting/
  reimplementing the protocol elektroid's `connectors/elektron.c`
  demonstrates working (sample upload/download, +Drive filesystem
  navigation) - not chasing the manual's SDS claim, which the most credible
  independent source directly contradicts. This should be verified against
  real hardware before being trusted either way, the same discipline the CT
  investigation applied before writing any code.
- **Open licensing question** (elektroid is GPLv3, shmample has no declared
  licence) is worth resolving before committing to "port the relevant
  pieces" the way `device.py`'s docstring describes doing for the P-6 code.

---

## 8. Source repositories

- `dagargo/elektroid` - github.com/dagargo/elektroid (GPLv3, C, GTK+CLI) -
  the load-bearing reference for the real Elektron file-transfer protocol,
  with explicit Digitakt II support.
- `mzero/elk-herd` - unofficial Elektron device manager (Elm, WebMIDI
  browser app); GitHub repo migrated to a personal site the author has
  asked not to be crawled by automation.
- `feamster/digitakt-midi-mcp` - github.com/feamster/digitakt-midi-mcp
  (MIT, Python) - live-control MCP server only, no transfer protocol.
- Elektron Digitakt II User Manual (EN, OS1.15A) - official documentation,
  source for §§1-5 above.
