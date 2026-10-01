"""Short synthesised cue sounds (no audio files needed).

Cues are deliberately neutral: the same "robot is back" chime plays after
success and after failure in every condition, so sound never tells the
participant more than the condition allows.
"""
import math
from array import array

import pygame

from game import settings

# name -> (list of (frequency Hz or 0 for a rest, seconds), relative gain)
CUES = {
    "robot_back": ([(659, 0.12), (880, 0.32)], 1.0),
    "input_needed": ([(1047, 0.09), (0, 0.05), (1047, 0.16)], 0.8),
    "reminder": ([(1047, 0.09), (0, 0.05), (1047, 0.09), (0, 0.05),
                  (1319, 0.2)], 0.9),
    "activity_done": ([(784, 0.06), (988, 0.1)], 0.3),
    "all_done": ([(523, 0.1), (659, 0.1), (784, 0.1), (1047, 0.3)], 0.7),
}


def _synthesise(notes, gain):
    rate, _, channels = pygame.mixer.get_init()
    samples = array("h")
    volume = settings.SOUND_VOLUME * gain * 32767
    for freq, duration in notes:
        count = int(rate * duration)
        for i in range(count):
            t = i / rate
            value = 0.0
            if freq:
                envelope = min(1.0, t / 0.005) * math.exp(-4.0 * t / duration)
                value = envelope * (math.sin(2 * math.pi * freq * t)
                                    + 0.3 * math.sin(4 * math.pi * freq * t))
                value /= 1.3
            sample = int(value * volume)
            for _ in range(channels):
                samples.append(sample)
    return pygame.mixer.Sound(buffer=samples.tobytes())


class SoundBank:
    """Plays named cues; silently does nothing if audio is unavailable."""

    def __init__(self, enabled):
        self.sounds = {}
        if not enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(44100, -16, 2, 512)
            for name, (notes, gain) in CUES.items():
                self.sounds[name] = _synthesise(notes, gain)
        except pygame.error as exc:
            print(f"[sounds] audio disabled: {exc}")
            self.sounds = {}

    def play(self, name):
        sound = self.sounds.get(name)
        if sound:
            sound.play()