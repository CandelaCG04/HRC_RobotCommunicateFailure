"""A* search on the 4-connected tile grid."""
import heapq
from itertools import count


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(world, start, goal, extra_blocked=frozenset()):
    """Return the tiles from start to goal (both included), or None.

    Start and goal are always treated as passable, so an agent can leave or
    return to a blocked tile such as the armchair. ``extra_blocked`` adds
    temporary obstacles (e.g. the other agent's tile).
    """
    start, goal = tuple(start), tuple(goal)
    if start == goal:
        return [start]

    def passable(tile):
        if tile in (start, goal):
            return True
        return world.is_walkable(tile) and tile not in extra_blocked

    tie = count()   # tie-breaker so heapq never compares tiles
    frontier = [(manhattan(start, goal), next(tie), start)]
    came_from = {start: None}
    cost = {start: 0}
    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == goal:
            path = []
            while current is not None:
                path.append(current)
                current = came_from[current]
            return path[::-1]
        for nxt in world.neighbors(current):
            if not passable(nxt):
                continue
            new_cost = cost[current] + 1
            if new_cost < cost.get(nxt, float("inf")):
                cost[nxt] = new_cost
                came_from[nxt] = current
                priority = new_cost + manhattan(nxt, goal)
                heapq.heappush(frontier, (priority, next(tie), nxt))
    return None
