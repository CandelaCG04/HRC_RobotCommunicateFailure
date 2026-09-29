"""The participant's character: an older adult with reduced mobility."""
from game import settings
from game.core.movement import Mover


class Avatar(Mover):
    """Sits in the armchair; walks slowly when fetching something alone."""

    def __init__(self, world, seat_tile):
        super().__init__(world, seat_tile, settings.AVATAR_SPEED)
        self.seat = tuple(seat_tile)
        self.carrying = None

    @property
    def walking(self):
        return self.moving or self.tile != self.seat
