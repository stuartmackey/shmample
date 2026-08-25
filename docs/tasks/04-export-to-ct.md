
# Aim

Investigation of how we could implement the sending of a pack to the Circuit Tracks (CT) device

1. Can we understand the structure of the samples on the device 
2. What is the simplest UI that can allow a pack to be sent to a device
3. How much control do we have over the layout of the sampels on the device
4. Can we test sending samples to as a prototype

# Additional information

In this case we are focusing on sending the samples onto an SD card rather than connecting the device via USB.

# Review notes

I've read both PDFs already in `docs/reference/` against the goals above.

- **Programmer's reference guide** (22 pages) is entirely MIDI CC/SysEx parameter
  tables - nothing about files, storage, or the SD card. Not useful for goal 1.
- **User guide** covers Packs/microSD at a device-UI level only, and what it says
  changes the shape of this task:
  - A "Pack" is "everything currently saved" on the device - all 64 Project
    memories, all 128 synth Patches and all 64 drum Samples - not a per-sample or
    per-slot unit.
  - The manual states **"Packs may be sent to Circuit Tracks using Novation
    Components"** (novationmusic.com's own app), not by writing files onto the
    card directly. The warning against removing the card mid-Save/Load ("Save
    operations include... transferring content from Components") reads as the
    device managing an opaque on-card format itself, not one Novation has
    published.
  - Unlike the P6's openly documented `IMPORT/BANK_x/PAD_y/*.WAV` drop, there's
    no equivalent "just copy files here" structure described anywhere in either
    PDF.
  - The card is confirmed FAT32, Class 10 minimum - so it's readable as a normal
    filesystem, but *what's on it* isn't documented.

- **Goal 1 is the load-bearing one** - goals 2-4 (UI, layout control, a send
  prototype) can't really be scoped until it's answered, since they all assume
  writable files with a known structure exists to target. Worth treating this
  doc as pure investigation for now (mirrors how `03-handling-multiple-devices.md`
  started broad and got narrowed via corrections) rather than committing to a UI
  or prototype goal before goal 1 has an answer.

- **On "SD card rather than USB"**: worth double-checking this is actually a
  choice being made for convenience. The user guide says the CT's "USB port does
  not carry audio" and describes sample upload as going through Components, not
  as a mass-storage file copy - so USB may not be a file-transfer path at all,
  making SD-card-via-a-card-reader the only host-accessible route rather than
  one of two options.

- **Suggested next step for goal 1**: since Novation hasn't published an on-card
  format in either PDF, the practical options are (a) get a real SD card that's
  had a Pack saved to it from a device and inspect it directly, or (b) look for
  existing community reverse-engineering of the Circuit/Circuit Tracks Pack
  format (the original Circuit has been out since 2017, so prior art may exist).
  Worth deciding which of these - or both - before promising a UI/prototype
  timeline.

# Review notes, round 2

`docs/reference/circuit-tracks-transfer-notes.md` (compiled from Novation's own
manuals plus the community project `namirsab/circuit-tracks-tools`) answers
goal 1 with much more certainty than the round-1 notes above could, and
supersedes a couple of things I said there.

- **SD-card-direct-write is confirmed impossible, not just undocumented.**
  Novation's User Guide states outright that Packs "may be sent to Circuit
  Tracks using Novation Components" and "may only be removed via Components",
  and that the device does not expose Pack storage as a generic writable
  filesystem - the only Mass-Storage behaviour it exposes is an unrelated
  fixed `TRACKS` folder for a "Getting Started" shortcut. This means the
  task's own "Additional information" note above - focusing on the SD card
  route rather than USB - is built on the assumption I flagged as needing
  confirmation, and that assumption turns out to be wrong: **USB (MIDI SysEx)
  is the only viable transfer path**, not an alternative to the SD card.
- **A reverse-engineered File Management SysEx protocol exists** (undocumented
  by Novation, from `namirsab/circuit-tracks-tools`) covering directory
  listing and read/write for three file types: projects (`0x03`), patches
  (`0x04`), and drum samples (`0x05`). Directory listing and project/patch
  write are confirmed working in that library; **drum sample write (`0x05`)
  is not implemented anywhere and is only a hypothesis** ("generalise
  `send_ncs_project()` to accept a file_type parameter") - this is the actual
  remaining unknown behind goal 1, not the SD card question.
- **Terminology collision worth resolving early**: a CT "Pack" (Novation's
  term - the totality of 64 Projects, 128 Patches and 64 Samples, swappable
  wholesale via the SD card and Components) is a much bigger, different thing
  from shmample's own `Pack` (a named holding-list of staged sample files, see
  `config_store.py`). Sending a shmample pack to a CT almost certainly means
  writing individual samples into slots 0-63 of the device's **currently
  loaded** Pack over SysEx, not building/replacing a CT-level Pack on the SD
  card - worth stating that explicitly in this doc's goals so "send to CT"
  isn't read as "export a `.circuittrackspack`" by mistake.
- **New dependency implication**: `pyproject.toml` currently has no MIDI
  library at all (just `textual`/`textual-plotext`). A CT send path needs one
  (e.g. `mido` + `python-rtmidi`), which is a materially different shape of
  code to `device.py`'s current plain-filesystem-copy `send_configuration` -
  worth deciding whether to depend on `namirsab/circuit-tracks-tools`
  directly (it's on PyPI, MIT-licensed) or port the relevant pieces the way
  `device.py`'s own docstring says the P-6 code was ported from p6-lab rather
  than imported, to keep shmample self-contained.
- **Revised suggested next step for goal 4**: before any UI work, the
  highest-value/lowest-cost experiment is testing whether file type `0x05`
  drum-sample write actually works against real hardware, using a throwaway
  sample slot - everything else in this doc depends on that one unconfirmed
  hypothesis panning out.

# Review notes, round 3 - live hardware test

Tried the direct-SD-write experiment for real against Stuart's own CT card
(self-formatted, packs added via Components), read-only over a card
reader/adapter:

- **The card layout on disk matches the reverse-engineered protocol exactly.**
  `Tracks/<NN_PackName>/{PCM,Sessions,Patches,meta}/`, one file per
  project/patch/sample, human-readable. `.ncs` project files are exactly
  160,780 bytes each - the precise size `circuit-tracks-transfer-notes.md`
  documents for SysEx file type `0x03`. Every `.wav` on the card is mono,
  16-bit, **48kHz** (not the P-6's 44.1kHz). A Pack needs only
  `meta/00_META.ncm` (2 bytes) + a `PCM/` folder to be valid - `Sessions/`
  and `Patches/` are absent on a couple of the sample-only factory packs, so
  a samples-only Pack is a legitimate, minimal shape.
- **The card mounted read-only on every computer tried** (this machine via a
  USB adapter, and separately a MacBook via the same physical adapter) -
  confirmed at the kernel level (`Write Protect is on` in `dmesg`, not just a
  mount option), so this wasn't a driver/OS quirk on one machine.
- **Decisive result**: reinserting the card into the CT itself and sending a
  sample to it via Components worked. So the card isn't damaged or
  permanently locked - **only the CT's own write path can write to it**.
  Whatever causes a generic PC card reader to see it as write-protected,
  the device's own handling of the same card isn't affected by it.

**Conclusion for this task**: this is real-hardware confirmation of what
round 2's notes already concluded from documentation alone - direct
host-side writes to the SD card are not a usable transfer path, full stop.
No amount of adapter/reader troubleshooting is going to change that; it's
not the bottleneck, it's the answer. The only route in is the MIDI SysEx
File Management protocol (§§2-8 of `circuit-tracks-transfer-notes.md`), and
the one thing actually left to verify for goal 4 is whether drum-sample
write (file type `0x05`) works over that protocol - everything else in this
doc's goals now follows from that.

# Review notes, round 4 - live MIDI protocol capture (major findings)

Installed the real reverse-engineering library (`circuit-tracks-tools` on
PyPI - the notes above had the package name slightly wrong; it's not
`circuit_tracks`) as a dev dependency and worked directly against Stuart's
CT over USB MIDI (ALSA port `Circuit Tracks:0`, visible as `hw:3,0,0`).

**Directory listing (file type `0x05`) works exactly as documented** -
`list_directory(midi, file_type=0x05)` returned all 64 drum-sample slot
names correctly on the first try, matching `circuit-tracks-transfer-notes.md`
§3 precisely.

**But it never reflected a Pack switch.** Loaded a different Pack on the
device (confirmed audibly/visually) and re-ran the same listing - identical
result, byte-for-byte. This matched a concern Stuart raised directly: the
installed library's `file_id()` helper hardcodes a `0` in the position later
found to be the pack-index byte (see below), so every read/write via this
library silently targets pack index 0 regardless of what's active on the
device. **This is a real, confirmed limitation of `circuit-tracks-tools` as
published** - not of the underlying device protocol.

**Root cause found by capturing real Novation Components traffic.** Two
capture methods were used:

1. `aseqdump -p <CT port>` - simple, but **only sees the device's own
   outgoing replies**, not commands Components sends to the device (an ALSA
   sequencer read-subscription is one-directional). Useful for confirming
   reply formats and slot names, but structurally incapable of showing a
   real `WRITE_DATA` payload.
2. `usbmon` (raw USB bus capture, root-only, via
   `/sys/kernel/debug/usb/usbmon/<bus>u`) - sees **both directions** as raw
   4-byte USB-MIDI event packets, which then need reassembling into logical
   SysEx messages (`F0...F7`) by hand. This is what actually cracked it.

**Confirmed: there is an undocumented pack-index byte.** The file-id triple
that both `circuit-tracks-transfer-notes.md` and the installed library
describe as `[file_type, slot_hi, slot_lo]` is, in real Components traffic,
actually `[file_type, pack_index, slot_within_pack]`. Two independent live
captures confirm this on both sides of the wire:

- Reply-only capture (`aseqdump`): device ACKs during a real Components
  "send samples" operation carried `file_id = (5, 26, N)` for `N = 0..15`.
- Full bidirectional capture (`usbmon`) of uploading one custom sample onto
  a pad: host's own `DIR_CONTROL`/query messages and the real `WRITE_DATA`
  blocks both carried `file_id`/query payloads of `(_, 19, N)`.

Both `26` and `19` are values inside the empty pack-slot range Stuart
described (device Packs 13-28 unused) - consistent with each capture
targeting whichever empty pack slot Components had been pointed at that
time. `list_directory`'s hardcoded `0` explains exactly why round 4's
opening test never reflected the on-device Pack switch: it was always
silently addressing pack index 0 (the internal Pack), never "whatever's
active".

**Confirmed: `WRITE_DATA` (subcmd `0x02`) genuinely carries real sample
audio**, and it's visible once captured from the correct direction. One
real "upload a custom sample to a pad" operation produced 46 `WRITE_DATA`
messages (up to 4757 bytes each) across 9 sample file-ids
(`(5, 19, 0)` .. `(5, 19, 8)`), each broken into multiple ~4KB-raw blocks -
**smaller than the 8192-byte block size `send_ncs_project()` uses for
project files**, so sample writes likely need their own, smaller block
size, not projects' constant reused as-is.

**New, still-undocumented protocol pieces found, not in the community
notes or the installed library at all:**

- **File type `0x02`** - lists the *Pack* directory itself (not a
  project/patch/sample). `FILE_ENTRY` replies for this type gave pack names
  and confirmed the SD card's folder names 1:1 (e.g. pack slot 1 =
  `"00_Synthwave"`).
- **File type `0x07`** - appeared once at the end of the real sample-upload
  capture, small (3-byte) `WRITE_DATA`. Likely the pack's `meta/*.ncm` file
  (which is itself only 2 bytes on the SD card) - unconfirmed.
- **Subcommand `0x0D`** (host→device) - sent 144 times before any real
  write, each with a 3-byte payload `[file_type, pack_index, N]` for
  `N = 0..143`, paired with a **subcommand `0x05`** device reply (fixed
  12-byte payload). Reads like a per-slot "does this need updating" change
  -detection pass Components runs before actually writing anything - this
  almost certainly explains round 4's earlier puzzle (sending an *unchanged*
  pack produced lots of traffic but zero real `WRITE_DATA`: Components
  correctly determined nothing needed re-uploading).

**Open question, not yet resolved**: decoding a real `WRITE_DATA` block's
bytes with the documented MSB-interleave scheme does not produce a
recognisable WAV header (`RIFF`/`WAVE`) at the start of a sample's first
block, unlike what's sitting in plain sight on the SD card's own `.wav`
files. Either there's a framing/offset detail specific to file type `0x05`
that wasn't captured/decoded correctly here, or the on-wire sample format
differs from the SD card's own plain-WAV representation and gets converted
by the device on save. This needs resolving with more captures/decoding
before attempting a real write ourselves with any confidence it'll produce
audible, correct audio rather than corrupt data landing in a real pack slot.

**Bottom line**: goal 1 and goal 3 are now substantially answered by real
hardware evidence, not just hypothesis - pack-level addressing exists, is
reachable, and drum-sample write is confirmed to genuinely happen over
`WRITE_DATA` (not merely a hoped-for generalisation). What remains before
goal 4's "test sending samples as a prototype" is safe to attempt for real:
nail down the exact sample write framing (block size, any header Components
sends that wasn't captured, the file type `0x07` meta write), and decode
enough of a captured block to confirm it really is raw/derived PCM audio
before writing anything of our own to a real device.

# Review notes, round 5 - direct SD write actually works end-to-end (corrects round 2/3)

Round 2 and round 3 concluded direct host writes to the SD card were "not a
usable transfer path, full stop", based on the card mounting read-only on
every reader tried at the time. That conclusion turns out to have been
wrong, and the write-protect issue was purely a **faulty full-size
microSD-to-SD adapter**, not anything card- or device-level:

- Bought/tried a different reader (a direct microSD reader, no full-size SD
  adapter sleeve involved) - the same card mounted **read-write** on the
  first try, confirmed both by the kernel (`/sys/block/sdc/ro` = `0`, not
  `1`) and by an actual successful write.
- With genuine write access, tried the exact experiment this doc originally
  set out to test: hand-built a new Pack folder directly on the SD card -
  `Tracks/11_Shmample Test/meta/00_META.ncm` (copied byte-for-byte from an
  existing zero-Sessions pack) + `Tracks/11_Shmample Test/PCM/00_....wav`
  (a generated 440Hz test tone, mono/16-bit/48kHz to match every other wav
  already on the card) - using the minimal Pack shape confirmed back in
  round 3's read-only inspection. No `Sessions/`/`Patches/` folders, no
  SysEx involved anywhere.
- **Novation Components recognised it immediately**: its own "Send pack to
  Circuit Tracks" pack-picker listed "Shmample Test" as a fully-formed pack
  in the grid, styled identically to every real pack - not flagged as
  broken/incomplete.
- **The CT hardware itself loaded it and played the sample perfectly** via
  its own Packs View, on real hardware, no computer/Components involved in
  that last step at all.

**This is now proven end-to-end, by hand, with a plain filesystem write.**
Round 2/3's "impossible" conclusion should be read as "impossible with a
faulty adapter", not "impossible in general" - worth remembering if this
comes up again, since it's an easy trap: a card reporting hardware
write-protect is worth suspecting the *reader* before concluding anything
about the card or the device's intentions.

**Practical implication for this task - this changes the recommended
implementation path substantially.** Round 4's MIDI SysEx protocol work
(pack-index addressing, `WRITE_DATA`, the undocumented subcommands) is
still valid, real, and worth keeping documented - but it is no longer the
only, or the simplest, route to "send a pack to a CT". Building the CT
export feature as a **plain filesystem write to the SD card**, mirroring
`device.py`'s existing P-6 `send_configuration` pattern almost exactly
(mount the card, write `Tracks/<NN>_<name>/{meta/00_META.ncm, PCM/*.wav}`,
fsync, done), is now the proven, lowest-risk, no-new-dependency option:

- No MIDI library needed at all for this path (the `mido`/`python-rtmidi`
  dev dependency added for round 4's investigation can stay dev-only/be
  removed if the SD-write path is what gets built).
- Directly reuses the existing `device.py` durability pattern (explicit
  fsync of file + directory chain up to the mount root) that
  `send_configuration` already established for the P-6, for the same
  removable-media reasons.
- Sidesteps every open question from round 4 (exact sample write framing,
  block size, the undocumented `0x07` meta write) entirely, since none of
  that machinery is needed once a plain file write is confirmed sufficient.

**Remaining open item**: this only reaches Pack slots that live on the SD
card (device Packs 2-32). The internal-only Pack 1 (factory "Waves" kit)
has no SD-card representation at all and can only ever be reached over
MIDI SysEx - out of scope unless a future task specifically needs to
target it.

# Scope decision

Stuart: eventually both transfer methods should be supported (direct SD
write, and MIDI SysEx for cases the SD route can't reach - e.g. the
internal-only Pack 1, or a future no-card-removal workflow), but **for now,
implementation work focuses on the direct SD card path only**. The round 4
SysEx protocol findings stay documented above as-is for when that second
method gets picked up later, rather than being acted on now.
