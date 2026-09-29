"""Smooth grid movement shared by the robot and the human avatar."""
import pygame

from game import settings
from game.core.pathfinding import astar


class Mover:
    """An agent that follows A* paths across the grid at a fixed speed."""

    def __init__(self, world, tile, speed_tiles_per_s):
        self.world = world
        self.tile = tuple(tile)
        self.pos = pygame.Vector2(world.tile_center(self.tile))
        self.speed = speed_tiles_per_s * settings.TILE
        self.path = []
        self.moving = False

    def set_speed(self, tiles_per_s):
        self.speed = tiles_per_s * settings.TILE

    def plan(self, goal, extra_blocked=frozenset()):
        """Return the A* path to ``goal`` without moving."""
        return astar(self.world, self.tile, goal, extra_blocked)

    def go_to(self, goal, extra_blocked=frozenset()):
        """Plan a path to ``goal`` and start moving along it."""
        path = astar(self.world, self.tile, goal, extra_blocked)
        if path is None:
            raise RuntimeError(f"No path from {self.tile} to {goal}")
        self.path = path[1:]
        self.moving = True

    def update(self, dt):
        """Advance along the path. Returns True on the frame of arrival."""
        if not self.moving:
            return False
        remaining = self.speed * dt
        while self.path and remaining > 0:
            target = pygame.Vector2(self.world.tile_center(self.path[0]))
            offset = target - self.pos
            distance = offset.length()
            if distance <= remaining:
                self.pos = target
                self.tile = self.path.pop(0)
                remaining -= distance
            else:
                self.pos += offset * (remaining / distance)
                remaining = 0
        if not self.path:
            self.moving = False
            return True
        return False
