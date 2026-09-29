"""The home-care robot as a moving agent with an LCD face."""
from game import settings
from game.core.movement import Mover

FACES = ("neutral", "happy", "sad", "thinking")


class Robot(Mover):
    """Moves around the house; shows a face and what it is carrying."""

    def __init__(self, world, home_tile):
        super().__init__(world, home_tile, settings.ROBOT_SPEED)
        self.home = tuple(home_tile)
        self.face = "neutral"
        self.carrying = None
        self.working = False        # searching / grasping animation
