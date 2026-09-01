#!/usr/bin/env python3
"""Digitakt II MIDI sniffing proxy.

Sits between Elektron Transfer and a real Digitakt II so we can capture the
real SysEx traffic Transfer sends for sample/project transfer. See
docs/reference/digitakt-2-transfer-notes.md for why this is the experiment
worth running: the manual's claim that the device speaks standard MIDI
Sample Dump Standard is disputed by the community, and the open-source
`elektroid` reference implementation has an unresolved macOS build issue -
so the most reliable way to learn the real protocol on macOS is to capture
it straight from Elektron's own app while it talks to real hardware.

Requires only `python-rtmidi` (not part of shmample's own dependencies -
this is a standalone research script, run on the tester's machine, not
part of the shmample package):

    pip install python-rtmidi

Usage:

    python3 digitakt2_midi_sniff.py

The script looks for a MIDI port with "Digitakt" in its name and creates
two virtual ports named "Digitakt II Proxy". In Elektron Transfer's
CONNECTIONS page, connect to "Digitakt II Proxy" instead of the real
"Digitakt II" ports. Then use Transfer completely normally - explore the
device, drag a sample or a project across, whatever we want to learn about.
Every message that crosses the proxy in either direction is relayed
immediately to/from the real hardware (so Transfer and the device behave
exactly as if directly connected) and logged to
`digitakt2_sniff_<timestamp>.log` in the current directory.

If port auto-detection doesn't find the device, run with --list to see all
available MIDI ports and pass --device-in/--device-out with the exact port
names (or a substring) to use instead.
"""

from __future__ import annotations

import argparse
import datetime
import sys

try:
    import rtmidi
except ImportError:
    print("This script needs python-rtmidi: pip install python-rtmidi", file=sys.stderr)
    raise

PROXY_NAME = "Digitakt II Proxy"


def find_port(ports: list[str], substring: str) -> int | None:
    substring = substring.lower()
    for index, name in enumerate(ports):
        if substring in name.lower():
            return index
    return None


def hexdump(message: list[int]) -> str:
    return " ".join(f"{byte:02X}" for byte in message)


class Logger:
    def __init__(self, path: str) -> None:
        self._file = open(path, "a", encoding="utf-8")
        print(f"Logging to {path}")

    def log(self, direction: str, message: list[int]) -> None:
        timestamp = datetime.datetime.now().isoformat(timespec="milliseconds")
        line = f"{timestamp} {direction:12s} len={len(message):5d}  {hexdump(message)}"
        self._file.write(line + "\n")
        self._file.flush()
        preview = hexdump(message[:16]) + (" ..." if len(message) > 16 else "")
        print(f"{direction:12s} len={len(message):5d}  {preview}")


class Relay:
    """Forwards every message to `forward_out` immediately, and logs it -
    reassembling SysEx that arrives split across multiple callbacks, since
    that's not guaranteed to arrive as a single chunk."""

    def __init__(self, direction: str, forward_out: "rtmidi.MidiOut", logger: Logger) -> None:
        self._direction = direction
        self._forward_out = forward_out
        self._logger = logger
        self._sysex_buffer: list[int] = []

    def __call__(self, event: tuple[list[int], float], data=None) -> None:
        message, _delta_time = event
        self._forward_out.send_message(message)
        self._accumulate_and_log(message)

    def _accumulate_and_log(self, message: list[int]) -> None:
        if message and message[0] == 0xF0:
            self._sysex_buffer = list(message)
        elif self._sysex_buffer:
            self._sysex_buffer.extend(message)
        else:
            self._logger.log(self._direction, message)
            return

        if self._sysex_buffer and self._sysex_buffer[-1] == 0xF7:
            self._logger.log(self._direction, self._sysex_buffer)
            self._sysex_buffer = []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list available MIDI ports and exit")
    parser.add_argument("--device-in", default="digitakt", help="substring to match the Digitakt's MIDI input port")
    parser.add_argument("--device-out", default="digitakt", help="substring to match the Digitakt's MIDI output port")
    args = parser.parse_args()

    probe_in = rtmidi.MidiIn()
    probe_out = rtmidi.MidiOut()
    in_ports = probe_in.get_ports()
    out_ports = probe_out.get_ports()

    if args.list:
        print("MIDI inputs:")
        for name in in_ports:
            print(f"  {name}")
        print("MIDI outputs:")
        for name in out_ports:
            print(f"  {name}")
        return

    device_in_index = find_port(in_ports, args.device_in)
    device_out_index = find_port(out_ports, args.device_out)
    if device_in_index is None or device_out_index is None:
        print("Could not find the Digitakt's MIDI ports automatically.", file=sys.stderr)
        print("Run with --list to see what's available, then pass --device-in/--device-out.", file=sys.stderr)
        sys.exit(1)

    print(f"Real device input:  {in_ports[device_in_index]}")
    print(f"Real device output: {out_ports[device_out_index]}")

    # "Real" ports: the actual Digitakt II hardware.
    real_in = rtmidi.MidiIn()
    real_in.ignore_types(sysex=False, timing=True, active_sense=True)
    real_in.open_port(device_in_index)
    real_out = rtmidi.MidiOut()
    real_out.open_port(device_out_index)

    # Virtual ports: what Elektron Transfer connects to instead.
    proxy_in = rtmidi.MidiIn()
    proxy_in.ignore_types(sysex=False, timing=True, active_sense=True)
    proxy_in.open_virtual_port(PROXY_NAME)
    proxy_out = rtmidi.MidiOut()
    proxy_out.open_virtual_port(PROXY_NAME)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = Logger(f"digitakt2_sniff_{timestamp}.log")

    # Transfer -> proxy_in -> (logged) -> real_out -> real device.
    proxy_in.set_callback(Relay("HOST->DEVICE", real_out, logger))
    # Real device -> real_in -> (logged) -> proxy_out -> Transfer.
    real_in.set_callback(Relay("DEVICE->HOST", proxy_out, logger))

    print(f"\nProxy ports open as \"{PROXY_NAME}\".")
    print("In Elektron Transfer's CONNECTIONS page, connect to those instead of the real Digitakt II.")
    print("Use Transfer normally. Press Ctrl+C here when done.\n")

    try:
        while True:
            input()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        real_in.close_port()
        real_out.close_port()
        proxy_in.close_port()
        proxy_out.close_port()
        print("\nStopped.")


if __name__ == "__main__":
    main()
