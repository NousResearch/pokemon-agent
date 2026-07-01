"""Unit tests for the ``a_until_dialog_end`` action loop.

Regression guard: the loop must keep pressing A while the game reports an
active dialog and stop once it clears. Dialog state is nested under
``state["dialog"]["active"]`` (see ``read_dialog`` and the state builder, and
the same access pattern in ``autopilot.py`` / ``dashboard/history.py``). The
loop previously read a non-existent top-level ``"dialog_active"`` key, so the
lookup always returned the default ``False`` and the loop broke after a single
A press — never advancing multi-box NPC dialogs.
"""

import pytest

from pokemon_agent import server


class _FakeEmulator:
    def __init__(self):
        self.a_presses = 0

    def press(self, button, *args):
        if button == "a":
            self.a_presses += 1

    def tick(self, *args):
        pass


@pytest.mark.asyncio
async def test_loops_until_dialog_clears(monkeypatch):
    fake = _FakeEmulator()
    monkeypatch.setattr(server, "_emulator", fake)

    # Dialog stays active for three checks, then clears.
    states = [
        {"dialog": {"active": True}},
        {"dialog": {"active": True}},
        {"dialog": {"active": True}},
        {"dialog": {"active": False}},
    ]
    idx = {"i": 0}

    def fake_state():
        i = min(idx["i"], len(states) - 1)
        idx["i"] += 1
        return states[i]

    monkeypatch.setattr(server, "_get_state_dict", fake_state)

    await server._execute_action("a_until_dialog_end")

    # Three presses while the dialog is active, plus the one that observed it
    # clear. With the old "dialog_active" lookup this was always exactly 1.
    assert fake.a_presses == 4


@pytest.mark.asyncio
async def test_respects_max_iteration_cap(monkeypatch):
    fake = _FakeEmulator()
    monkeypatch.setattr(server, "_emulator", fake)
    # Dialog never clears -> must stop at the 10-iteration (300-frame) cap.
    monkeypatch.setattr(server, "_get_state_dict", lambda: {"dialog": {"active": True}})

    await server._execute_action("a_until_dialog_end")

    assert fake.a_presses == 10


@pytest.mark.asyncio
async def test_stops_immediately_when_no_dialog(monkeypatch):
    fake = _FakeEmulator()
    monkeypatch.setattr(server, "_emulator", fake)
    monkeypatch.setattr(server, "_get_state_dict", lambda: {"dialog": {"active": False}})

    await server._execute_action("a_until_dialog_end")

    assert fake.a_presses == 1
