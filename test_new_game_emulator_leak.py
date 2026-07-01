"""Regression test for the "New Game" emulator leak.

`POST /games/new` rebuilds the emulator from the ROM. It must shut down the
old PyBoy instance (via `emulator.close()`) before overwriting the module
global, otherwise every "New Game" leaks the previous emulator.

This test never touches a real ROM or PyBoy: `create_emulator` is monkeypatched
to hand out lightweight stubs that record their create/close order.
"""

import pytest

from pokemon_agent import server
from pokemon_agent.server import GameConfig, new_game, NewGameRequest


# Shared event log: ("create", n) / ("close", n) in the order they happen.
_EVENTS: list = []


class StubEmulator:
    """Stand-in for a real Emulator; records lifecycle events."""

    def __init__(self, n: int):
        self.n = n
        self.closed = False
        _EVENTS.append(("create", n))

    def tick(self, frames: int = 1) -> None:  # called by new_game
        pass

    def close(self) -> None:
        self.closed = True
        _EVENTS.append(("close", self.n))


class StubSession:
    def __init__(self):
        self.id = "sid-test"
        self.name = "test"
        self.game = "red"
        self.hermes_session_id = None
        self.objectives = []
        self.stats = {}

    def to_dict(self):
        return {"id": self.id, "name": self.name, "game": self.game}


class StubSessionManager:
    def create(self, name=None, game="red"):
        return StubSession()

    def save(self, gs):
        return gs


@pytest.fixture
def wired(monkeypatch):
    """Wire up server globals with stubs and hand out a fresh emulator per call."""
    _EVENTS.clear()
    counter = {"n": 0}

    def fake_create_emulator(rom_path):
        counter["n"] += 1
        return StubEmulator(counter["n"])

    # new_game does `from pokemon_agent.emulator import create_emulator`, so we
    # patch it at its source module.
    monkeypatch.setattr("pokemon_agent.emulator.create_emulator", fake_create_emulator)

    monkeypatch.setattr(server, "_config",
                        GameConfig(rom_path="fake.gb", game_type="red"))
    monkeypatch.setattr(server, "_session_mgr", StubSessionManager())
    monkeypatch.setattr(server, "_active_session", None)

    # A pre-existing emulator (as after startup); n=0 so real ones start at 1.
    pre = StubEmulator(0)
    monkeypatch.setattr(server, "_emulator", pre)
    return pre


async def test_new_game_closes_old_emulator(wired):
    # First New Game: replaces the pre-existing emulator (n=0).
    await new_game(NewGameRequest(name="one"))
    assert wired.closed, "pre-existing emulator was not closed on New Game"
    first = server._emulator
    assert isinstance(first, StubEmulator) and first.n == 1

    # Second New Game: must close the first-created emulator before making a new one.
    await new_game(NewGameRequest(name="two"))
    assert first.closed, "emulator from the previous New Game leaked (close() not called)"

    second = server._emulator
    assert second.n == 2 and not second.closed

    # Ordering: every emulator is closed before its successor is created.
    assert _EVENTS == [
        ("create", 0),
        ("close", 0), ("create", 1),
        ("close", 1), ("create", 2),
    ], f"unexpected lifecycle order: {_EVENTS}"
