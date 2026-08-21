from pathlib import Path

from textual.binding import Binding
from textual.widgets import Static

from shmample import device
from shmample.device import DeviceState


class DevicePanel(Static):
    """Very narrow status line: is a P-6 connected, and in what mode.

    Modelled on lazygit's own tiny "Status" pane (repo + branch, one
    line) rather than a full pane's worth of content - fixed height, not
    a share of the column like the other three panes.
    """

    DEFAULT_CSS = """
    DevicePanel {
        height: 3;
        border: round $foreground;
    }
    DevicePanel:focus {
        border: round $primary;
    }
    """

    # can_focus so numbered pane-jump (1, see app.py) has somewhere to
    # land, same reasoning as PreviewInfo.
    can_focus = True

    # check_action below hides whichever of these doesn't apply to the
    # current state, so the footer only ever shows the one that'd
    # actually do something - lazygit-style, one action per situation.
    BINDINGS = [
        Binding("u", "unmount", "Unmount"),
        Binding("m", "mount", "Mount"),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.state: DeviceState | None = None

    def on_mount(self) -> None:
        self.show(None)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        state = self.state
        if action == "unmount":
            return state is not None and state.connected and state.mount is not None
        if action == "mount":
            return state is not None and not state.connected and state.unmounted_device is not None
        return True

    def show(self, state: DeviceState | None) -> None:
        self.state = state
        if state is None:
            text = "Checking for a P-6..."
        elif state.connected and state.mode is not None:
            text = f"P-6 connected -> {state.mode}"
        elif state.connected:
            text = "P-6 connected (mode not recognised)"
        elif state.unmounted_device is not None:
            text = f"P-6 detected ({state.unmounted_device}), not mounted"
        else:
            text = "P-6 not connected"
        self.update(text)
        # check_action's answer for "unmount"/"mount" just changed - tell
        # the Footer (or anything else showing bindings) to re-ask it.
        self.refresh_bindings()

    def action_unmount(self) -> None:
        state = self.state
        if state is None or not state.connected or state.mount is None:
            return
        self.update(f"Unmounting {state.mount}...")
        self.run_worker(self._unmount(state.mount), exclusive=True, group="unmount", name="unmount")

    async def _unmount(self, mount: Path) -> None:
        await device.unmount(mount)
        # Re-detect from scratch rather than assuming success - if
        # unmount() failed the drive is still there, and this shows that
        # rather than claiming it's gone.
        new_state = await device.detect_device_state_async()
        self.app.device_state = new_state
        self.show(new_state)

    def action_mount(self) -> None:
        state = self.state
        if state is None or state.connected or state.unmounted_device is None:
            return
        self.update(f"Mounting {state.unmounted_device}...")
        self.run_worker(self._mount(state.unmounted_device), exclusive=True, group="mount", name="mount")

    async def _mount(self, block_device: Path) -> None:
        await device.mount_device(block_device)
        # Same reasoning as _unmount above - re-detect rather than assume
        # the mount attempt actually landed.
        new_state = await device.detect_device_state_async()
        self.app.device_state = new_state
        self.show(new_state)
