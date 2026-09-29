"""Global settings for the home-care robot game.

Every number you are likely to tweak after piloting (speeds, timings,
limits) lives here, so the rest of the code never hard-codes them.
"""
from pathlib import Path

# ----------------------------------------------------------------- paths
GAME_DIR = Path(__file__).resolve().parent
CONFIG_DIR = GAME_DIR / "config"
PROJECT_ROOT = GAME_DIR.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"

# ---------------------------------------------------------------- layout
# +--------------------------+-----------------------------+
# |  house map (ambient view |  info: part, timer, goal,   |
# |  of where the robot is)  |  robot screen, your list    |
# +--------------------------+-----------------------------+
# |  robot band: status,     |  side task: knit a scarf    |
# |  message, answer buttons |                             |
# +--------------------------+-----------------------------+
# Everything the participant acts on is in the bottom band, side by side.
TILE = 28                       # pixel size of one grid tile
GRID_COLS = 22
GRID_ROWS = 16
MAP_W = TILE * GRID_COLS        # 616
MAP_H = TILE * GRID_ROWS        # 448
SCREEN_W = 1180
SCREEN_H = 726
BAND_H = SCREEN_H - MAP_H       # 278
INFO_RECT = (MAP_W, 0, SCREEN_W - MAP_W, MAP_H)
ROBOT_RECT = (0, MAP_H, MAP_W, BAND_H)
SIDE_TASK_RECT = (MAP_W, MAP_H, SCREEN_W - MAP_W, BAND_H)
FPS = 60

# ---------------------------------------------------------------- speeds
ROBOT_SPEED = 3.0               # tiles per second
# Default only: self-fetch speed is scaled so each trip takes
# SELF_FETCH_TIME seconds.
AVATAR_SPEED = 1.0

# ------------------------------------------------------- timings (seconds)
ACK_TIME = 1.5                  # robot confirms the request before leaving
WORK_TIME = 2.0                 # robot searching / grasping at the target
DELIVER_TIME = 2.0              # robot hands an item over
# Failure feedback is shown this long before the decision buttons appear.
# Identical in every condition, so timing is not a confound. The message
# stays in the speech bubble afterwards, so long messages can be finished.
FEEDBACK_TIME = 3.0
# "I'll get it myself" always costs the same total time, wherever the item
# is, so the cost does not differ between items, parts or conditions.
SELF_FETCH_TIME = 30.0
SELF_PICKUP_TIME = 1.5          # part of SELF_FETCH_TIME spent picking up
BLOCK_END_DELAY = 1.0           # pause after the last item of a block

# ----------------------------------------------------------------- rules
MAX_ATTEMPTS = 5                # "Try again" disappears after this many
BLOCK_TIME_LIMIT = 60          # soft deadline shown as a countdown
MINIGAME_ENABLED = True
KNIT_ROW_TIME = 8.0             # seconds one scarf row takes to knit
USE_TTS = False                 # can also be switched on with --tts

# ------------------------------------------------------------ attention cues
SOUND_ENABLED = True            # switch off with --mute
SOUND_VOLUME = 0.5
# If the robot is waiting for the participant this long, one reminder
# sound plays (once per waiting period). Set to None to disable.
REMINDER_AFTER = 8.0

# --------------------------------------------------------------- colours
COLORS = {
    "bg": (34, 36, 46),
    "panel": (246, 244, 239),
    "panel_line": (210, 206, 196),
    "highlight": (226, 234, 248),
    "text": (40, 40, 48),
    "text_muted": (125, 125, 135),
    "warning": (205, 70, 60),
    "wall": (62, 66, 80),
    "door": (214, 198, 170),
    "living": (238, 227, 204),
    "kitchen": (216, 228, 234),
    "bedroom": (229, 221, 238),
    "button": (255, 255, 255),
    "button_hover": (224, 234, 250),
    "button_border": (160, 170, 190),
    "pending": (195, 195, 200),
    "success": (84, 164, 104),
    "alt": (80, 132, 205),
    "self": (224, 152, 62),
    "gave_up": (190, 96, 96),
    "robot_body": (222, 226, 232),
    "robot_outline": (88, 94, 110),
    "robot_screen": (28, 38, 54),
    "robot_face": (120, 230, 255),
    "skin": (240, 205, 176),
    "hair": (228, 228, 232),
    "cardigan": (116, 138, 182),
    "cane": (120, 84, 52),
    "bubble": (255, 255, 255),
    "badge": (255, 250, 220),
}
