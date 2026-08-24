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
- **Circuit Tracks support doesn't exist yet**: `device.py` is entirely Roland
  P-6 specific (bank A-H/pad 1-6). "Circuit Tracks" doesn't appear anywhere else
  in the codebase or docs. Decide whether Circuit Tracks support is in scope for
  this task or a stated prerequisite/follow-up.
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
- **ConfigList and knock-on UI**: `ConfigList` currently lists one file as one
  pack+layout. If a pack can hold multiple device configs, something needs to
  let the user see/create/select among a pack's device configs - no such widget
  exists yet. Also decide whether `HoldingArea`'s "a" (assign) chord still
  deep-links straight into the device screen, or becomes a separate step.
