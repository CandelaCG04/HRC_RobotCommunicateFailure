"""Text wrapping for speech bubbles and optional text-to-speech."""
import queue
import threading


def wrap_text(text, font, max_width):
    """Split ``text`` into lines that fit ``max_width`` pixels."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if font.size(trial)[0] <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


class Voice:
    """Speaks robot lines on a background thread (needs ``pyttsx3``).

    If TTS is disabled or pyttsx3 is missing, ``say`` does nothing, so the
    game always runs.
    """

    def __init__(self, enabled):
        self.enabled = enabled
        self._queue = queue.Queue()
        self._thread = None
        if enabled:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def say(self, text):
        if self.enabled and text:
            self._queue.put(text)

    def _run(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 150)
        except Exception as exc:        # noqa: BLE001 - any failure = no TTS
            print(f"[voice] text-to-speech disabled: {exc}")
            self.enabled = False
            return
        while True:
            text = self._queue.get()
            if text is None:
                break
            engine.say(text)
            engine.runAndWait()

    def close(self):
        if self._thread:
            self._queue.put(None)
