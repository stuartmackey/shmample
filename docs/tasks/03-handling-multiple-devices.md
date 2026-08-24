# aim

I want to split the creation of a "pack" of samples from the type of device they will be sent to. This means that the user can create a group of samples and define multiple device configurations for the set of samples. So they can set up how it should go to a p6 or a circuit tracks and persist it.

# Tasks

- split the pack creation and the device configuration into separate screen layouts
- first is just sample selection into the holding area
- second is picking a device and assigning the samples in the holding area into the device layout

# Open questions / prerequisites (review notes)

- **Data model**: `Configuration` (`config_store.py`) currently bundles the
  device-agnostic `holding` list and a single P-6-specific
  `assignments: dict[(bank, pad) -> path]` into one object/JSON file. Supporting
  "multiple device configurations for the set of samples" means splitting this
  into a pack (holding) plus a list of per-device configurations, each with its
  own device type + assignments. Needs its own schema design, not just UI work.

Correction, i am considering this an opportunity to rework the data model. We would create "packs", the would then have a one to many relationship with configurations. The connfiguration would map samples from the pack to a device. the devices would have to allow for very differnt parameters and structure.

The p6 is banks and pads
The CT is channels and pads


- **Circuit Tracks support doesn't exist yet**: `device.py` is entirely Roland
  P-6 specific (bank A-H/pad 1-6). "Circuit Tracks" doesn't appear anywhere else
  in the codebase or docs. Decide whether Circuit Tracks support is in scope for
  this task or a stated prerequisite/follow-up.

the device pane would need to be able to detect a device that has been attached (or a sd card with appropriate configuration.)

- **Screen vs pane toggle**: `app.py` already has a `display = False` toggle
  parking `AssignmentGrid`, explicitly commented as an experiment towards a
  two-screen direction, not a committed pushed `Screen`. Decide which of these
  this task means - a real pushed `Screen` must follow CLAUDE.md's rules for new
  panes/screens (`Footer`, numbered `border_title`/`Binding`, its own
  `action_focus_pane`).


- **Migration path**: existing saved configuration JSON files use the old
  single-assignments schema. `config_store._from_json` already has one
  precedent (`.get("holding", [])`) for old files missing a newer field; the
  pack/device-config split needs the same treatment.

they can be purged, there is nothing we need to keep

  - **ConfigList and knock-on UI**: `ConfigList` currently lists one file as one
  pack+layout. If a pack can hold multiple device configs, something needs to
  let the user see/create/select among a pack's device configs - no such widget
  exists yet. Also decide whether `HoldingArea`'s "a" (assign) chord still
  deep-links straight into the device screen, or becomes a separate step.

This has been explained earlier



*** Additional information

- we do not need to implement support for any devices right now.
- we just need to update the UI to cope with the idea of two stages in the configuration

- Pane for sample maintenance

1.1) List of packages
1.2) Sample browser
1.3) Preview

2.1) Tag List

3.1) Holding Area

- Pane for device configuration

1.1) Device
1.2) Holding Area

2.1) P6 configuration, banks and pads as is currently implemented

2.1) CT configurationn

2.1.1) Channel list (Drum 1, Drum 2, Drum 3, Drum 4)
2.1.2) Pad list 1-64

# Review notes on the update above

- **Scope, resolved**: full `Pack`/`Configuration` data model rework is in
  scope for this task, not deferred. CT gets a real assignment shape
  (channel/pad) and a real UI grid alongside P6's, but no actual
  detection/send-to-device code for CT - that stays a named, modelled,
  UI-only device type until a later task gives it hardware support.
- **Still open - device detection scope**: "the device pane would need to be
  able to detect a device that has been attached (or an SD card with
  appropriate configuration)" reads as new detection logic beyond today's
  P6-only `device.detect_or_mount`. Since CT hardware support is explicitly
  out of scope, does the device pane need to *distinguish* P6 vs. CT at all
  in this task, or does it stay P6-only detection with CT only reachable by
  manually picking "CT" when creating a configuration?
- **Still open - duplicate pane numbering**: the second screen lists both
  "2.1) P6 configuration" and "2.1) CT configuration" under the same number.
  If these are two views that swap into one pane depending on the
  configuration's device type, that's a single numbered/focusable pane. If
  they're meant to be two separately-focusable panes, they need distinct
  numbers - CLAUDE.md requires each pane's `border_title`/`Binding` number to
  be unique on its screen.
- **Still open - browsing a pack's existing configurations**: the
  Pack/Configuration relationship answers the data-model half of the
  original "ConfigList and knock-on UI" question, but the layout above still
  doesn't show a widget for seeing/picking among a pack's *existing*
  configurations (e.g. a pack that already has a P6 config, when the user
  wants to open it again rather than start a new one). Worth a line in the
  layout for this - likely on the device configuration screen, alongside
  "1.1) Device" / "1.2) Holding Area".

# Correction - scope narrowed further

The "full model rework now" answer above is superseded. This task does
**not** build the Pack-to-many-Configurations relationship or any
device-specific assignment shape (P6 bank/pad vs. CT channel/pad), and does
**not** touch device detection - `device.py` stays exactly as it is.

What this task does do: rename and restructure the *pack* half only (today's
`holding` list, currently just a field bolted onto `Configuration`) into its
own properly-named, properly-structured thing, on the understanding that
`Configuration` will gain the device-specific fields (device type, its own
assignment shape, the link back to a pack) in a later task. This means the
earlier "Still open" items above are resolved for this task's purposes:

- Device detection: out of scope, no change to `device.py`.
- Multi-device `Configuration` data model: out of scope, deferred entirely.
- Browsing a pack's existing configurations: moot for now, since a pack
  doesn't yet support more than the one configuration it already has.

**Pack restructure, resolved**: extract a real `Pack` dataclass (name,
description, created_at, modified_at, holding) out of `Configuration`,
rather than just renaming a field in place. For this task it still lives in
the same JSON file/object as `Configuration` - `Configuration` holds a
`Pack` instance plus its existing `assignments` field unchanged. No new
file format or store split yet; that's for the later task that adds the
one-to-many relationship and per-device assignment shapes.
