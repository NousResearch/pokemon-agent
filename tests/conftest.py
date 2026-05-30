"""Shared pytest fixtures.

Unit tests (tests/unit) are PURE — no emulator, run on the host `.venv`.
Integration tests (tests/integration) are marked ``@pytest.mark.emulator`` and
are auto-skipped when the mgba bindings aren't importable (i.e. outside the
devbox), so the host run collects only the fast pure tests.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROMS = ROOT / "roms"

# This playthrough's fixed trainer IDs (determine which PIDs are shiny).
TID = 51376
SID = 36462


@pytest.fixture(scope="session")
def golden():
    """Known-good constants reused across tests."""
    return {
        "tid": TID,
        "sid": SID,
        # write-seed 0x55FF2959 on route3_grass.ss1 -> Hasty shiny Spearow:
        "hasty_spearow_seed": 0x55FF2959,
        "hasty_spearow_species": 21,
        "hasty_spearow_ivs": (31, 31, 17, 31, 19, 31),
        "lonely_nidoran_ivs": (27, 31, 14, 31, 23, 16),
    }


def _state_fixture(name):
    @pytest.fixture
    def _f():
        p = ROMS / name
        if not p.exists():
            pytest.skip(f"state {name} not present")
        return str(p)
    return _f


rom_path = _state_fixture("Pokemon - LeafGreen Version (USA).gba")
route3_grass_state = _state_fixture("leafgreen_route3_grass.ss1")
spearow_best_state = _state_fixture("leafgreen_shiny_spearow_best.ss1")
nidoran_best_state = _state_fixture("leafgreen_shiny_nidoranm_best.ss1")


def _mgba_available():
    try:
        import mgba  # noqa: F401
        return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """Auto-skip @pytest.mark.emulator tests when mgba isn't importable."""
    if _mgba_available():
        return
    skip = pytest.mark.skip(reason="mgba not available (run integration tests in the devbox)")
    for item in items:
        if "emulator" in item.keywords:
            item.add_marker(skip)
