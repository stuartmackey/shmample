# Novation Circuit Tracks — Content Transfer Reference

Research notes on how projects, patches, samples, and packs get on and off a
Novation Circuit Tracks (CT). Compiled from Novation's own documentation
(User Guide v3, Programmer's Reference Guide) and the community
reverse-engineering project `namirsab/circuit-tracks-tools` (MIT licence,
PyPI package `circuit_tracks`). Intended as reference material for another
AI coding agent working on CT tooling.

---

## 1. Two separate transfer mechanisms exist

**Synth patches — officially documented by Novation.**
Fixed 350-byte SysEx messages: `Replace Current Patch`, `Replace Patch`, and
`Patch Dump Request`. The 340-byte patch body (name, category,
oscillator/filter/LFO/mod-matrix parameters) is documented at fixed byte
offsets in the Programmer's Reference Guide.

**Projects, patches (again), and drum samples — undocumented by Novation,
reverse-engineered from Novation Components' own Web MIDI traffic.**
This is the interesting one and is the subject of the rest of this document.
Source: `namirsab/circuit-tracks-tools`, specifically `docs/sysex-file-protocol.md`
and `src/circuit_tracks/ncs_transfer.py`.

---

## 2. The reverse-engineered File Management SysEx protocol

All messages share a common header:

```
F0 00 20 29 01 64 03 <subcmd> <payload...> F7
```

| Field | Bytes | Value | Meaning |
|---|---|---|---|
| SysEx start | 1 | `F0` | Standard MIDI SysEx start |
| Manufacturer | 3 | `00 20 29` | Novation |
| Product type | 1 | `01` | Synth |
| Product number | 1 | `64` | Circuit Tracks (100) |
| Command group | 1 | `03` | File management protocol |
| Sub-command | 1 | varies | see table below |
| Payload | N | varies | message-specific |
| SysEx end | 1 | `F7` | Standard MIDI SysEx end |

### Sub-commands

| SubCmd | Name | Direction | Purpose |
|---|---|---|---|
| `0x40` | OPEN_SESSION | Host→Device | Start file management session |
| `0x41` | CLOSE_SESSION | Host→Device | End session |
| `0x0b` | DIR_CONTROL | Host→Device | Directory listing control |
| `0x09` | QUERY_INFO | Host→Device | Request device/version info |
| `0x01` | WRITE_INIT | Host→Device | Begin file write (metadata); also doubles as READ_REQUEST with a `02` flag |
| `0x02` | WRITE_DATA | Host→Device | File data chunk |
| `0x03` | WRITE_FINISH | Host→Device | End file write (checksum) |
| `0x07` | SET_FILENAME | Host→Device | Set filename for slot |
| `0x04` | ACK | Device→Host | Acknowledge (matches address) |
| `0x0c` | FILE_ENTRY | Device→Host | File listing entry |

### File types

| Type byte | Contents | Slots | Notes |
|---|---|---|---|
| `0x03` | Project files (`.ncs`) | 0–63 | 160,780 bytes each |
| `0x04` | Synth patches | 0–63 | 340 bytes each |
| `0x05` | Drum samples (`.wav`) | 0–63 | size varies |

### File ID

A 3-byte value identifying a target file: `<type> <slot_hi> <slot_lo>`. Slot
is a 14-bit value split across two 7-bit bytes.
Example: `03 00 01` = project slot 1.

---

## 3. Directory listing

1. `OPEN_SESSION` (0x40)
2. `DIR_CONTROL` [0x01] — device ACKs
3. `QUERY_INFO` [0x01, 0x00] — device responds with version info
4. `DIR_CONTROL` [0x02] — device responds with current filename (`FILE_ENTRY`, subcmd `0x0C`)
5. `DIR_CONTROL` [file_type, 0x00] — device responds with:
   - DIR_CONTROL ACK: `0x0b <file_type> 00 3f 00`
   - then 64× FILE_ENTRY: `0x0c <file_type> <slot> <filename bytes>`
6. `CLOSE_SESSION` (0x41)

Implementation: `list_directory()` in `ncs_transfer.py`. **This works for all
three file types (0x03/0x04/0x05)** — you can enumerate what's on the device
for projects, patches, *or* samples.

---

## 4. Writing a project (~29 SysEx messages)

```
Step  SubCmd  Description
───── ─────── ────────────────────────────────────
  1   0x40    OPEN SESSION
  2   0x0b    DIR_CONTROL: 0x0b 01
  3   0x09    QUERY_INFO:  0x09 01 00
  4   0x0b    DIR_CONTROL: 0x0b 02
  5   0x0b    DIR_CONTROL: 0x0b 03 00  (list projects)
  6   0x01    WRITE_INIT (address 0, file_id, size)
  7   0x02    WRITE_DATA block 1  (8192 bytes → ~9363 encoded)
  ...
 25   0x02    WRITE_DATA block 19
 26   0x02    WRITE_DATA block 20 (partial)
 27   0x03    WRITE_FINISH (CRC32)
 28   0x07    SET_FILENAME
 29   0x41    CLOSE SESSION
```

The device ACKs each WRITE message; wait for the ACK before sending the next
block. Implementation: `send_ncs_project()` in `ncs_transfer.py`.

### Block addressing

Each WRITE message has an 8-byte address field (only the last two bytes used):

```
00 00 00 00 00 00 <page> <offset>
```

16 offsets per page (`0x00`–`0x0F`), then the page increments. `WRITE_INIT`
is block 0; `WRITE_DATA` starts at block 1. `WRITE_FINISH` is the block after
the last data block. Helper: `block_address()`.

### WRITE_INIT payload

```
<8-byte address=0> <3-byte file_id> 01 00 00 00 <5 size nibbles>
```

Size nibbles = file size as hex nibbles, MSN first. E.g. 160,780 = `0x2740C`
→ `02 07 04 00 0c`.

### WRITE_DATA payload

```
<8-byte address> <3-byte file_id> <MSB-interleave-encoded data>
```

### WRITE_FINISH payload

```
<8-byte address> <3-byte file_id> <8 CRC32 nibbles>
```

CRC32 = standard `zlib.crc32()` of the raw (unencoded) file data.

### SET_FILENAME payload

```
<3-byte file_id> <ASCII filename>
```

---

## 5. Data encoding: MSB interleave

MIDI SysEx requires every byte to be < 0x80. Every 7 raw data bytes are
encoded as 8 output bytes:

```
[MSB_header] [d0 & 0x7F] [d1 & 0x7F] ... [d6 & 0x7F]
```

MSB header: bit *N* holds the MSB of data byte *N* (bits 0–6). To decode:

```
original = (data & 0x7F) | (((header >> N) & 1) << 7)
```

Expansion ratio is 8/7. The last group in a file may be partial.
Implementation: `encode_msb_interleave()` / `decode_msb_interleave()`.

---

## 6. Patch save (special two-phase case)

The documented `Replace Patch` SysEx (`0x01`, command group `0x00`) is
**silently ignored** unless preceded by a "flash unlock" step:

**Phase 1 — file management session (unlocks flash writes):**
1. Open session
2. Directory handshake (same as §3 above)
3. Query patch directory entries — send `WRITE_INIT` with file type `0x04`
   for each entry in the page
4. Close session

**Phase 2 — Replace Patch SysEx** (command group `0x00`, *not* `0x03`):

```
F0 00 20 29 01 64 01 00 00 <slot> 00 <340 patch bytes> F7
```

- Command `0x01` = Replace Patch
- Location byte: `0x00` = synth 1, `0x01` = synth 2

Implementation: `send_patch_to_slot()` in `ncs_transfer.py`.

---

## 7. Reading a project

Reuses the same sub-commands as writing, in reverse. The host sends a
single READ request; the device streams the whole project back.

```
Step  SubCmd  Dir           Description
───── ─────── ───────────── ────────────────────────────────────
  1   0x01    Host→Device   READ_REQUEST (WRITE_INIT with 0x02 flag)
  2   0x01    Device→Host   READ_INIT response (file size)
  3   0x02    Device→Host   READ_DATA block 1  (9383 bytes encoded)
  ...
 22   0x02    Device→Host   READ_DATA block 20 (partial, 5886 bytes)
 23   0x03    Device→Host   READ_FINISH (CRC32)
 24   0x41    Host→Device   CLOSE SESSION
```

No per-block ACKs from the host — the device streams continuously.

- **READ_REQUEST payload** (WRITE_INIT with read flag):
  `<8-byte address=0> <3-byte file_id> 02` — the `02` byte is the read flag
  (vs `01` for write). Example, project slot 36:
  `00 00 00 00 00 00 00 00 03 00 24 02`.
- **READ_INIT response**: same shape as WRITE_INIT but Device→Host; confirms
  file size.
- **READ_DATA blocks**: same shape as WRITE_DATA but Device→Host.
- **READ_FINISH**: device sends CRC32; host should validate against
  `zlib.crc32()` of the reassembled raw data.

Implementation: `receive_ncs_project()` in `ncs_transfer.py`.

---

## 8. What's actually implemented today in `circuit_tracks` (as of cloning)

- `list_directory()` — **works for all three file types** (0x03/0x04/0x05).
- `send_ncs_project()` / `receive_ncs_project()` — full working read/write,
  but **hardcoded to file type 0x03 (projects) only**. The internal
  `file_id()` helper bakes in `_FILE_TYPE_PROJECT` and does not take a
  file-type parameter.
- `send_patch_to_slot()` — full working write for file type 0x04 (patches),
  via the two-phase unlock approach in §6.
- **No working send/receive for file type 0x05 (drum samples) exists in the
  library.** The protocol table documents that type 0x05 exists and is
  listable, but nobody has confirmed a working write path for samples.

**Practical implication:** the WRITE_INIT/WRITE_DATA/WRITE_FINISH/SET_FILENAME
sequence appears generic across file types by design (only the file_type
byte changes), so generalising `send_ncs_project()` to accept a file_type
parameter is a plausible path to sample transfer — but this is an
**unverified hypothesis**, not a confirmed-working path, and should be
tested carefully against real hardware (small/disposable sample slots first)
before being relied on.

---

## 9. The `.circuittrackspack` container format

Separate from the wire protocol above — this is just a **zip file**, used by
Novation Components and the community "Web Tracks" app. Not itself a SysEx
concept.

```
index.json
projects/project_N.ncs
samples/sample_N.wav
patches/patch_N.syx
```

`index.json` shape:

```json
{
  "name": "Pack Name",
  "product": "circuit-tracks",
  "version": "1.0",
  "projects": [{"name": "...", "url": "projects/project_0.ncs"}, ...],
  "samples":  [{"name": "...", "url": "samples/sample_0.wav"}, ...],
  "patches":  [{"name": "...", "url": "patches/patch_0.syx"}, ...]
}
```

Each array entry is just `{name, url}`. Packaging/unpacking this is plain
zip work (Python stdlib `zipfile` is sufficient). Actually getting the
contents *onto* the device still goes through the SysEx protocol above, one
project/patch/sample at a time — the zip container itself is never sent to
the device as a blob.

---

## 10. microSD card and Pack storage — what's actually possible

This corrects an earlier assumption that writing pack files directly to a
mounted SD card might be a viable transfer route. **It is not**, per
Novation's own User Guide:

- A microSD card in the rear-panel slot holds up to **31 additional Packs**
  (Circuit Tracks' internal flash memory always holds exactly one Pack), for
  up to 32 Packs total available for loading while the card is inserted.
- **Packs may only be sent to Circuit Tracks using Novation Components.**
  The User Guide states this explicitly: *"Packs may be sent to Circuit
  Tracks using Novation Components at components.novationmusic.com."*
- **Packs cannot be removed except via Components** — the User Guide states:
  *"Packs may only be removed via Components, and cannot be cleared from the
  device directly."*
- Loading a Pack from the card onto the device, and **duplicating** a Pack
  onto a new card slot, are both done **on the device itself** (Packs View:
  hold Shift + Projects), not via any host-side file operation.
- A Pack contains the totality of a "session": all 64 Project memories, all
  128 synth Patches, and all 64 drum Samples.
- **Card compatibility**: Class 10 minimum, FAT32 format.
- **The device does not expose the SD card's Pack storage as a generic
  writable filesystem to a host computer.** The only Mass-Storage-Device
  behaviour documented is the small **"Easy Start Tool"** — when connected
  via USB, CT can present a `TRACKS` folder containing a `Getting
  Started` HTML/URL shortcut to Novation Components/registration. This can
  be toggled on/off in Advanced Setup View (hold Shift while powering on,
  then press Note) but it is **not a general-purpose file-transfer channel**
  and has nothing to do with Pack contents.
- Card behaviour is explicitly **undefined** if a different microSD card is
  inserted without a power cycle first; a full power-down/power-up is
  required before loading a new card's content.

**Bottom line for tooling purposes:** unlike the Roland P-6 (which mounts as
a plain writable USB mass-storage volume for sample import/export), the
Circuit Tracks' Pack/SD storage is **not directly host-writable at all**.
Every documented and reverse-engineered write path — projects, patches, and
(hypothetically) samples — goes over the MIDI SysEx protocol in §§2–8, not
over a mounted filesystem. Any TUI built for CT needs a MIDI-based transfer
backend; there's no mass-storage shortcut available here.

---

## 11. Source repositories

- `namirsab/circuit-tracks-tools` — https://github.com/namirsab/circuit-tracks-tools
  (Python library `circuit_tracks`, MIT licence, published on PyPI; also
  includes a browser-based "Web Tracks" app and an MCP server built on the
  same library)
- Novation Circuit Tracks User Guide v3 (EN) — official documentation,
  source for §10
- Novation Circuit Tracks Programmer's Reference Guide — official
  documentation, source for the documented single-patch SysEx in §1
