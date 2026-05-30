"""Compatibility shim for the wild-shiny pipeline (kept so existing hunt scripts
keep importing `shiny_grass_core as C`). The implementation now lives in:

  * pokemon_agent.wild_enumerate  — PURE offline: enumerate + predict + select
  * pokemon_agent.gba_trigger     — EMULATOR: bundle, trigger, verify, confirm
  * pokemon_agent.gen3_rng        — PURE per-seed predictor (wild_outcome, …)

See docs/CANDIDATE_GEN_PLAN.md. New code should import the modules directly.
"""
from __future__ import annotations

from pokemon_agent.shiny_gen3 import LCG_ADD as LCG_C  # noqa: F401
from pokemon_agent.shiny_gen3 import LCG_MULT as LCG_A  # noqa: F401
from pokemon_agent.wild_enumerate import (  # noqa: F401
    NAT,
    _enum_range,
    _unpack_iv,
    enumerate_candidates,
    load_results,
    n31,
    predict_env_ivs,
    select_best,
)

# Emulator layer is imported lazily so pure offline use (and host unit tests)
# don't require mgba. Accessing any emulator name triggers the import.
_EMU_NAMES = {
    "ROM", "ENEMY", "RNG", "make_bundle", "jiggle_trigger", "verify_env",
    "confirm_candidates", "_verify_chunk",
}
_ALIASES = {"_bundle": "make_bundle", "_emulate": "jiggle_trigger"}


def __getattr__(name):  # PEP 562 module-level lazy attribute
    target = _ALIASES.get(name, name)
    if target in _EMU_NAMES:
        import pokemon_agent.gba_trigger as _t
        return getattr(_t, target)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
