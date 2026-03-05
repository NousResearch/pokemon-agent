"""
Pokemon Agent — A* Pathfinding on tile grids.

Provides grid-based pathfinding for navigating Pokemon game maps.
Tiles are addressed as (x, y) integer tuples.  The collision_map is a
dict of {(x, y): bool} where True means walkable.  If no collision_map
is provided every tile is assumed walkable.
"""

from __future__ import annotations

import heapq
from typing import Dict, List, Optional, Tuple

# Direction vectors: name -> (dx, dy)
DIRECTIONS: Dict[str, Tuple[int, int]] = {
    "up":    (0, -1),
    "down":  (0,  1),
    "left":  (-1, 0),
    "right": (1,  0),
}

# Reverse lookup: delta -> direction name
_DELTA_TO_DIR: Dict[Tuple[int, int], str] = {v: k for k, v in DIRECTIONS.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def manhattan(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """Manhattan distance heuristic."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def neighbors(
    pos: Tuple[int, int],
    collision_map: Optional[Dict[Tuple[int, int], bool]] = None,
) -> List[Tuple[Tuple[int, int], str]]:
    """Return walkable neighbors of *pos* as (neighbor_pos, direction) pairs.

    Parameters
    ----------
    pos:
        Current (x, y) position.
    collision_map:
        Mapping of (x, y) -> bool where True means passable.
        If *None*, every adjacent tile is considered walkable.

    Returns
    -------
    List of (neighbor_pos, direction_name) tuples for each reachable
    adjacent tile.
    """
    result: List[Tuple[Tuple[int, int], str]] = []
    x, y = pos
    for direction, (dx, dy) in DIRECTIONS.items():
        nx, ny = x + dx, y + dy
        neighbor = (nx, ny)
        if collision_map is None:
            # No collision data — assume all tiles walkable
            result.append((neighbor, direction))
        elif collision_map.get(neighbor, False):
            # Tile exists in map and is marked passable
            result.append((neighbor, direction))
    return result


# ---------------------------------------------------------------------------
# A* pathfinding
# ---------------------------------------------------------------------------

def find_path(
    start: Tuple[int, int],
    goal: Tuple[int, int],
    collision_map: Optional[Dict[Tuple[int, int], bool]] = None,
    max_iterations: int = 10_000,
) -> List[str]:
    """Find the shortest path from *start* to *goal* using A*.

    Parameters
    ----------
    start:
        Starting (x, y) tile position.
    goal:
        Target (x, y) tile position.
    collision_map:
        Dict of ``{(x, y): bool}``  — *True* marks a passable tile.
        When *None* every tile is assumed passable (useful for simple
        navigation without collision data).
    max_iterations:
        Safety limit to prevent runaway searches on large / open maps.

    Returns
    -------
    List of direction strings (``'up'``, ``'down'``, ``'left'``,
    ``'right'``) describing the path from *start* to *goal*.
    Returns an empty list if no path is found or start == goal.

    Examples
    --------
    >>> find_path((0, 0), (2, 0))
    ['right', 'right']

    >>> find_path((0, 0), (1, 1), {(0,0): True, (1,0): True, (1,1): True})
    ['right', 'down']
    """
    if start == goal:
        return []

    # Priority queue entries: (f_score, counter, position)
    # counter breaks ties so heapq never compares tuples
    counter = 0
    open_set: list[tuple[int, int, Tuple[int, int]]] = []
    heapq.heappush(open_set, (manhattan(start, goal), counter, start))

    # came_from maps position -> (parent_position, direction_taken)
    came_from: Dict[Tuple[int, int], Tuple[Tuple[int, int], str]] = {}

    g_score: Dict[Tuple[int, int], int] = {start: 0}

    closed: set[Tuple[int, int]] = set()

    iterations = 0

    while open_set and iterations < max_iterations:
        iterations += 1
        _f, _cnt, current = heapq.heappop(open_set)

        if current == goal:
            # Reconstruct path
            return _reconstruct(came_from, current)

        if current in closed:
            continue
        closed.add(current)

        current_g = g_score[current]

        for neighbor_pos, direction in neighbors(current, collision_map):
            if neighbor_pos in closed:
                continue

            tentative_g = current_g + 1

            if tentative_g < g_score.get(neighbor_pos, float("inf")):
                g_score[neighbor_pos] = tentative_g
                came_from[neighbor_pos] = (current, direction)
                f = tentative_g + manhattan(neighbor_pos, goal)
                counter += 1
                heapq.heappush(open_set, (f, counter, neighbor_pos))

    # No path found
    return []


def _reconstruct(
    came_from: Dict[Tuple[int, int], Tuple[Tuple[int, int], str]],
    current: Tuple[int, int],
) -> List[str]:
    """Walk backwards through came_from to build the direction list."""
    directions: List[str] = []
    while current in came_from:
        parent, direction = came_from[current]
        directions.append(direction)
        current = parent
    directions.reverse()
    return directions


# ---------------------------------------------------------------------------
# Action conversion
# ---------------------------------------------------------------------------

def directions_to_actions(directions: List[str]) -> List[str]:
    """Convert direction strings to ``walk_<dir>`` action strings.

    Parameters
    ----------
    directions:
        List of direction names, e.g. ``['up', 'up', 'right']``.

    Returns
    -------
    List of action strings: ``['walk_up', 'walk_up', 'walk_right']``.
    """
    return [f"walk_{d}" for d in directions]


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def navigate(
    start: Tuple[int, int],
    goal: Tuple[int, int],
    collision_map: Optional[Dict[Tuple[int, int], bool]] = None,
) -> List[str]:
    """High-level helper: find path and return action strings.

    Combines :func:`find_path` and :func:`directions_to_actions`.

    Returns
    -------
    List of ``walk_*`` action strings, or empty list if unreachable.
    """
    path = find_path(start, goal, collision_map)
    return directions_to_actions(path)


def path_length(
    start: Tuple[int, int],
    goal: Tuple[int, int],
    collision_map: Optional[Dict[Tuple[int, int], bool]] = None,
) -> int:
    """Return the number of steps in the shortest path, or -1 if unreachable."""
    path = find_path(start, goal, collision_map)
    return len(path) if path or start == goal else -1
