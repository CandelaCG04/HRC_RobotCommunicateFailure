"""The single, central definition of the emotion classes used throughout FEmotion.

The model's raw output order is remapped to this order (``MODEL_CLASSES`` in
``femotion.model``; its extra "contempt" class is dropped).
"""

EMOTIONS: tuple[str, ...] = (
    "angry",
    "disgust",
    "fear",
    "happy",
    "sad",
    "surprise",
    "neutral",
)

NUM_EMOTIONS = len(EMOTIONS)
