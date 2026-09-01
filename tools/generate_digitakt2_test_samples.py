#!/usr/bin/env python3
"""Generate the small test WAV files used by the Digitakt II MIDI sniff
experiment (see digitakt2_midi_sniff.md). Already 16-bit/48kHz, matching
the format Digitakt II's manual documents as native - so what Elektron
Transfer sends over the wire during the capture is (as far as we can tell)
whatever it does with an already-correctly-formatted file, not a
format-conversion side effect.

Re-run to regenerate: python3 generate_digitakt2_test_samples.py
"""

from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 48000
DURATION_SECONDS = 2.0
FADE_SECONDS = 0.02
OUT_DIR = Path(__file__).parent


def tone(frequency: float, duration: float = DURATION_SECONDS) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    signal = 0.5 * np.sin(2 * np.pi * frequency * t)

    fade_samples = int(SAMPLE_RATE * FADE_SECONDS)
    fade_in = np.linspace(0, 1, fade_samples)
    fade_out = fade_in[::-1]
    signal[:fade_samples] *= fade_in
    signal[-fade_samples:] *= fade_out

    return signal.astype(np.float32)


def main() -> None:
    mono = tone(440.0)
    mono_path = OUT_DIR / "digitakt2_test_tone_mono.wav"
    sf.write(mono_path, mono, SAMPLE_RATE, subtype="PCM_16")
    print(f"Wrote {mono_path} ({mono_path.stat().st_size} bytes, mono, 440Hz)")

    left = tone(440.0)
    right = tone(880.0)
    stereo = np.stack([left, right], axis=1)
    stereo_path = OUT_DIR / "digitakt2_test_tone_stereo.wav"
    sf.write(stereo_path, stereo, SAMPLE_RATE, subtype="PCM_16")
    print(f"Wrote {stereo_path} ({stereo_path.stat().st_size} bytes, stereo, 440Hz L / 880Hz R)")


if __name__ == "__main__":
    main()
