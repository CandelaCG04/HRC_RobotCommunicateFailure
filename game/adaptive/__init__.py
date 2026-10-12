"""Closed-loop failure-response behaviour (``--adaptive``): Sense - Think - Act.

    sensing.py       read the user's facial emotion from the shared database
    observations.py  turn one failure episode into emotion / decision / pause evidence
    hmm.py           belief over the hidden user state (receptive, frustrated,
                     disengaging), one update per failure episode
    policy.py        baseline schedule, heuristic rules, small MDP (Thompson-sampled
                     QMDP) and the per-user model it learns
    mind.py          RobotMind: beliefs, desires and intention (BDI) tying it together

No pygame here, so everything can be tested without a display.
"""
import json

from game import settings

CONFIG_PATH = settings.CONFIG_DIR / "adaptive.json"


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
