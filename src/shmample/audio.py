import asyncio
import shutil
import sys
from pathlib import Path

# Order matters: first found on PATH wins. paplay/pw-play are the lightest
# for a plain wav (native to a PipeWire/Pulse stack); ffplay/mpv are the
# fallback for setups without either.
LINUX_PLAYERS = ("paplay", "pw-play", "ffplay", "mpv")


class NoPlayerFoundError(Exception):
    """No usable audio player was found for this platform."""


def _linux_command(path: Path) -> list[str] | None:
    for name in LINUX_PLAYERS:
        if shutil.which(name) is None:
            continue
        if name == "ffplay":
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        if name == "mpv":
            return ["mpv", "--no-video", "--really-quiet", str(path)]
        return [name, str(path)]  # paplay/pw-play just take the path
    return None


def build_play_command(path: Path) -> list[str] | None:
    """The subprocess command to play `path`, or None if no player was found.

    Not consulted on Windows - winsound.PlaySound there is a direct stdlib
    call, not a subprocess (see Previewer.play).
    """
    if sys.platform == "darwin":
        return ["afplay", str(path)] if shutil.which("afplay") else None
    return _linux_command(path)


class Previewer:
    """Plays at most one preview at a time - starting a new one kills
    whatever was already playing rather than queuing behind it.

    Verified in `05-audio-preview.md`: cancelling the asyncio task alone
    does not kill the underlying OS process, only stops awaiting it - the
    explicit kill() in stop()/the finally block below is what actually
    does that.
    """

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    async def play(self, path: Path) -> None:
        await self.stop()

        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return

        command = build_play_command(path)
        if command is None:
            raise NoPlayerFoundError(
                "No audio player found on PATH "
                f"({', '.join(LINUX_PLAYERS)} on Linux, afplay on macOS)."
            )

        # A local reference, not just self._proc: if a later play() call
        # comes in while this one is still awaiting proc.wait(), it
        # reassigns self._proc to its own process. Cleaning up via
        # self._proc here (rather than this call's own `proc`) would then
        # kill that newer, unrelated process instead of this one.
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._proc = proc
        try:
            await proc.wait()
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

    async def stop(self) -> None:
        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
            return
        proc = self._proc
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        self._proc = None
