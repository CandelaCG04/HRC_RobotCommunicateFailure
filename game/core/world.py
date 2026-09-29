"""The house: tile grid, rooms, furniture and named spots.

Coordinates are (column, row) tile indices. Pixel positions are only
computed through ``tile_center`` so the logic stays resolution-independent.
"""
from dataclasses import dataclass

from game import settings

# '#' = wall, '.' = floor. Doors are floor tiles inside a wall line.
LAYOUT = (
    "######################",
    "#.........#..........#",
    "#.........#..........#",
    "#.........#..........#",
    "#....................#",   # door living room <-> kitchen at (10, 4)
    "#.........#..........#",
    "#.........#..........#",
    "#.........#####.######",   # door kitchen <-> bedroom at (15, 7)
    "#.........#..........#",
    "#.........#..........#",
    "#.........#..........#",
    "#....................#",   # door living room <-> bedroom at (10, 11)
    "#.........#..........#",
    "#.........#..........#",
    "#.........#..........#",
    "######################",
)


@dataclass(frozen=True)
class Room:
    name: str
    x: int
    y: int
    w: int
    h: int
    color_key: str
    label_tile: tuple

    def contains(self, tile):
        tx, ty = tile
        return (self.x <= tx < self.x + self.w
                and self.y <= ty < self.y + self.h)


@dataclass(frozen=True)
class Furniture:
    """A rectangle of tiles that blocks movement and is drawn on the map."""
    name: str
    x: int
    y: int
    w: int
    h: int
    color: tuple
    label: str = ""

    def tiles(self):
        return {(self.x + dx, self.y + dy)
                for dx in range(self.w) for dy in range(self.h)}


ROOMS = (
    Room("Living room", 1, 1, 9, 14, "living", (6, 12)),
    Room("Kitchen", 11, 1, 10, 6, "kitchen", (18, 5)),
    Room("Bedroom", 11, 8, 10, 7, "bedroom", (14, 11)),
)

FURNITURE = (
    # Living room
    Furniture("sofa", 1, 1, 4, 1, (122, 152, 122), "Sofa"),
    Furniture("tv_stand", 7, 1, 3, 1, (100, 80, 64), "TV"),
    Furniture("coffee_table", 2, 4, 3, 1, (176, 136, 96), "Table"),
    Furniture("armchair", 3, 7, 1, 1, (156, 92, 82)),
    Furniture("bookshelf", 1, 14, 4, 1, (128, 96, 70), "Bookshelf"),
    Furniture("plant", 9, 14, 1, 1, (92, 152, 92)),
    # Kitchen
    Furniture("counter", 11, 1, 6, 1, (172, 176, 182), "Counter"),
    Furniture("stove", 17, 1, 1, 1, (72, 72, 78)),
    Furniture("fridge", 19, 1, 2, 1, (238, 242, 246), "Fridge"),
    Furniture("kitchen_table", 14, 4, 3, 1, (176, 136, 96), "Table"),
    # Bedroom
    Furniture("desk", 11, 8, 3, 1, (142, 106, 76), "Desk"),
    Furniture("bed", 17, 10, 3, 4, (246, 246, 250), "Bed"),
    Furniture("nightstand", 20, 10, 1, 1, (128, 96, 70)),
    Furniture("wardrobe", 12, 14, 3, 1, (128, 96, 70), "Wardrobe"),
)

# Named places that items, the robot and the avatar refer to. Each is the
# free tile in front of a piece of furniture (except the armchair seat).
SPOTS = {
    "robot_home": (5, 7),
    "avatar_seat": (3, 7),
    "sofa": (2, 2),
    "tv_stand": (8, 2),
    "bookshelf": (2, 13),
    "counter": (13, 2),
    "fridge": (19, 2),
    "kitchen_table": (15, 5),
    "desk": (12, 9),
    "nightstand": (20, 11),
    "wardrobe": (13, 13),
    # Living-room side of the doors (used for navigation failures)
    "kitchen_door_outside": (9, 4),
    "bedroom_door_outside": (9, 11),
}


class World:
    """Static description of the house plus grid queries."""

    def __init__(self):
        self.rows = len(LAYOUT)
        self.cols = len(LAYOUT[0])
        if any(len(row) != self.cols for row in LAYOUT):
            raise ValueError("LAYOUT rows must all have the same length")
        if (self.cols, self.rows) != (settings.GRID_COLS, settings.GRID_ROWS):
            raise ValueError("LAYOUT size does not match settings.GRID_*")
        self.walls = {(x, y) for y, row in enumerate(LAYOUT)
                      for x, char in enumerate(row) if char == "#"}
        self.rooms = ROOMS
        self.furniture = FURNITURE
        self.spots = dict(SPOTS)
        self.blocked = set(self.walls)
        for piece in self.furniture:
            self.blocked |= piece.tiles()
        for name, tile in self.spots.items():
            if tile in self.blocked and name != "avatar_seat":
                raise ValueError(f"Spot '{name}' {tile} is not walkable")

    def in_bounds(self, tile):
        x, y = tile
        return 0 <= x < self.cols and 0 <= y < self.rows

    def is_walkable(self, tile):
        return self.in_bounds(tile) and tile not in self.blocked

    def neighbors(self, tile):
        x, y = tile
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if self.in_bounds(nxt):
                yield nxt

    def spot(self, name):
        try:
            return self.spots[name]
        except KeyError:
            known = ", ".join(sorted(self.spots))
            raise KeyError(f"Unknown spot '{name}'. Known: {known}") from None

    def room_at(self, tile):
        for room in self.rooms:
            if room.contains(tile):
                return room
        return None

    @staticmethod
    def tile_center(tile):
        half = settings.TILE / 2
        return (tile[0] * settings.TILE + half, tile[1] * settings.TILE + half)
