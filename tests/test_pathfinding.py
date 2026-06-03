"""Tests for pokemon_agent.pathfinding module."""

import pytest

from pokemon_agent.pathfinding import (
    find_path,
    navigate,
    directions_to_actions,
    neighbors,
    manhattan,
    path_length,
)


# ---------------------------------------------------------------------------
# manhattan distance
# ---------------------------------------------------------------------------

class TestManhattan:
    def test_same_point(self):
        assert manhattan((0, 0), (0, 0)) == 0

    def test_horizontal(self):
        assert manhattan((0, 0), (5, 0)) == 5

    def test_vertical(self):
        assert manhattan((0, 0), (0, 3)) == 3

    def test_diagonal(self):
        assert manhattan((1, 1), (4, 5)) == 7

    def test_negative_coords(self):
        assert manhattan((-2, -3), (2, 3)) == 10


# ---------------------------------------------------------------------------
# neighbors
# ---------------------------------------------------------------------------

class TestNeighbors:
    def test_no_collision_map_returns_four(self):
        result = neighbors((5, 5), None)
        assert len(result) == 4
        positions = {pos for pos, _ in result}
        assert positions == {(5, 4), (5, 6), (4, 5), (6, 5)}

    def test_collision_map_blocks_walls(self):
        cmap = {(1, 0): True, (0, 1): True, (-1, 0): False, (0, -1): False}
        result = neighbors((0, 0), cmap)
        positions = {pos for pos, _ in result}
        assert (1, 0) in positions
        assert (0, 1) in positions
        assert (-1, 0) not in positions
        assert (0, -1) not in positions

    def test_directions_are_correct(self):
        result = {d: pos for pos, d in neighbors((0, 0), None)}
        assert result["up"] == (0, -1)
        assert result["down"] == (0, 1)
        assert result["left"] == (-1, 0)
        assert result["right"] == (1, 0)


# ---------------------------------------------------------------------------
# find_path (A*)
# ---------------------------------------------------------------------------

class TestFindPath:
    def test_same_start_and_goal(self):
        assert find_path((0, 0), (0, 0)) == []

    def test_straight_horizontal(self):
        path = find_path((0, 0), (3, 0))
        assert path == ["right", "right", "right"]

    def test_straight_vertical(self):
        path = find_path((0, 0), (0, 2))
        assert path == ["down", "down"]

    def test_diagonal_no_collision(self):
        path = find_path((0, 0), (2, 2))
        assert len(path) == 4  # manhattan distance
        assert path.count("right") == 2
        assert path.count("down") == 2

    def test_with_collision_map(self):
        # Simple corridor: only specific tiles are walkable
        cmap = {
            (0, 0): True,
            (1, 0): True,
            (2, 0): True,
            (2, 1): True,
            (2, 2): True,
        }
        path = find_path((0, 0), (2, 2), cmap)
        assert path == ["right", "right", "down", "down"]

    def test_no_path_returns_empty(self):
        # Start is isolated
        cmap = {(0, 0): True}
        path = find_path((0, 0), (5, 5), cmap)
        assert path == []

    def test_max_iterations_limit(self):
        path = find_path((0, 0), (1000, 1000), max_iterations=10)
        assert path == []

    def test_path_around_wall(self):
        # Wall blocks direct path, must go around
        cmap = {}
        for x in range(5):
            for y in range(5):
                cmap[(x, y)] = True
        # Block the middle column
        cmap[(2, 0)] = False
        cmap[(2, 1)] = False
        cmap[(2, 2)] = False

        path = find_path((0, 1), (4, 1), cmap)
        assert len(path) > 0
        # Verify path doesn't go through walls
        pos = (0, 1)
        deltas = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
        for step in path:
            dx, dy = deltas[step]
            pos = (pos[0] + dx, pos[1] + dy)
            assert cmap.get(pos, False), f"Path went through wall at {pos}"
        assert pos == (4, 1)


# ---------------------------------------------------------------------------
# directions_to_actions
# ---------------------------------------------------------------------------

class TestDirectionsToActions:
    def test_conversion(self):
        dirs = ["up", "down", "left", "right"]
        assert directions_to_actions(dirs) == [
            "walk_up", "walk_down", "walk_left", "walk_right"
        ]

    def test_empty(self):
        assert directions_to_actions([]) == []


# ---------------------------------------------------------------------------
# navigate (high-level helper)
# ---------------------------------------------------------------------------

class TestNavigate:
    def test_returns_walk_actions(self):
        actions = navigate((0, 0), (2, 1))
        assert all(a.startswith("walk_") for a in actions)
        assert len(actions) == 3

    def test_same_position(self):
        assert navigate((3, 3), (3, 3)) == []


# ---------------------------------------------------------------------------
# path_length
# ---------------------------------------------------------------------------

class TestPathLength:
    def test_same_position(self):
        assert path_length((0, 0), (0, 0)) == 0

    def test_reachable(self):
        assert path_length((0, 0), (3, 2)) == 5

    def test_unreachable(self):
        cmap = {(0, 0): True}
        assert path_length((0, 0), (5, 5), cmap) == -1
