"""Gen 3 (Ruby/Sapphire/Emerald, FireRed/LeafGreen) shiny + RNG helpers.

Gen 3 shininess is **nothing like** Gen 2.  Gen 2 keys off DVs; Gen 3 keys
off the 32-bit Personality Value (PID) and the trainer IDs:

    shiny  ⇔  (TID ^ SID ^ (PID >> 16) ^ (PID & 0xFFFF)) < 8

IVs (0–31 each) live in a separate 32-bit word and do **not** affect
shininess — so unlike the Gold hunts, "shiny" and "good IVs" are
independent rolls of the same PID/IV generation sequence.

This module is pure logic (no emulator dependency) so it can be unit
tested directly, mirroring ``pokemon_agent/shiny.py`` for Gen 2.
"""

from __future__ import annotations

from dataclasses import dataclass

# Gen 3 shiny threshold.  A Pokémon is shiny when the xor of the four
# 16-bit halves of (OTID, PID) is below this value (8 of 65536 ≈ 1/8192).
SHINY_THRESHOLD = 8

U16 = 0xFFFF
U32 = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Shininess
# ---------------------------------------------------------------------------

def shiny_value(pid: int, tid: int, sid: int) -> int:
    """The Gen 3 shiny value P = TID ^ SID ^ hi(PID) ^ lo(PID).

    ``tid``/``sid`` are the visible Trainer ID and the hidden Secret ID
    (each 16-bit).  Shiny iff this is < ``SHINY_THRESHOLD``.
    """
    return (tid ^ sid ^ (pid >> 16) ^ (pid & U16)) & U16


def is_shiny(pid: int, tid: int, sid: int, threshold: int = SHINY_THRESHOLD) -> bool:
    return shiny_value(pid, tid, sid) < threshold


def is_shiny_otid(pid: int, otid: int, threshold: int = SHINY_THRESHOLD) -> bool:
    """Same check given the packed 32-bit OTID (TID = low 16, SID = high 16)."""
    return is_shiny(pid, otid & U16, (otid >> 16) & U16, threshold)


# ---------------------------------------------------------------------------
# IVs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Gen3IVs:
    """Individual Values (0–31) for a Gen 3 Pokémon.

    Note Gen 3 splits special into Special Attack and Special Defense
    (Gen 2 had a single Special DV).
    """
    hp: int
    attack: int
    defense: int
    speed: int
    sp_attack: int
    sp_defense: int
    is_egg: bool = False
    ability: int = 0

    @property
    def total(self) -> int:
        return (self.hp + self.attack + self.defense
                + self.speed + self.sp_attack + self.sp_defense)

    def as_tuple(self) -> tuple[int, int, int, int, int, int]:
        return (self.hp, self.attack, self.defense,
                self.speed, self.sp_attack, self.sp_defense)


def decode_ivs(iv_word: int) -> Gen3IVs:
    """Decode the 32-bit IV/egg/ability word from the Misc substructure.

    Bit layout (LSB first):
        HP:0–4  Atk:5–9  Def:10–14  Spd:15–19  SpA:20–24  SpD:25–29
        isEgg:30  ability:31
    """
    return Gen3IVs(
        hp=iv_word & 0x1F,
        attack=(iv_word >> 5) & 0x1F,
        defense=(iv_word >> 10) & 0x1F,
        speed=(iv_word >> 15) & 0x1F,
        sp_attack=(iv_word >> 20) & 0x1F,
        sp_defense=(iv_word >> 25) & 0x1F,
        is_egg=bool((iv_word >> 30) & 1),
        ability=(iv_word >> 31) & 1,
    )


# ---------------------------------------------------------------------------
# Encrypted data substructures
# ---------------------------------------------------------------------------

# The 48-byte encrypted block is four 12-byte substructures whose order is
# PID % 24.  Letters: G=Growth, A=Attacks, E=EVs/Condition, M=Misc.
SUBSTRUCTURE_ORDER = (
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
)

ENCRYPTED_BLOCK_SIZE = 48
SUBSTRUCT_SIZE = 12


def decrypt_block(block: bytes, pid: int, otid: int) -> bytes:
    """Decrypt the 48-byte encrypted block and return it reordered into
    canonical G,A,E,M order.

    Each 32-bit word of the block is XOR'd with ``pid ^ otid``, then the
    four substructures are permuted from their stored order (``pid % 24``)
    back to G,A,E,M so callers can index fields by fixed offsets.
    """
    if len(block) != ENCRYPTED_BLOCK_SIZE:
        raise ValueError(f"expected {ENCRYPTED_BLOCK_SIZE}-byte block, got {len(block)}")

    key = (pid ^ otid) & U32
    dec = bytearray(ENCRYPTED_BLOCK_SIZE)
    for i in range(0, ENCRYPTED_BLOCK_SIZE, 4):
        word = int.from_bytes(block[i:i + 4], "little")
        dec[i:i + 4] = ((word ^ key) & U32).to_bytes(4, "little")

    order = SUBSTRUCTURE_ORDER[pid % 24]
    canonical = bytearray(ENCRYPTED_BLOCK_SIZE)
    for stored_idx, letter in enumerate(order):
        dst = "GAEM".index(letter)
        src_off = stored_idx * SUBSTRUCT_SIZE
        dst_off = dst * SUBSTRUCT_SIZE
        canonical[dst_off:dst_off + SUBSTRUCT_SIZE] = \
            dec[src_off:src_off + SUBSTRUCT_SIZE]
    return bytes(canonical)


def ivs_from_decrypted(canonical: bytes) -> Gen3IVs:
    """Pull the IV word out of a canonical (G,A,E,M) decrypted block.

    The Misc substructure is the 4th (index 3); the IV/egg/ability word is
    at offset +4 within it.
    """
    misc_off = 3 * SUBSTRUCT_SIZE
    iv_word = int.from_bytes(canonical[misc_off + 4:misc_off + 8], "little")
    return decode_ivs(iv_word)


# ---------------------------------------------------------------------------
# Gen 3 RNG (linear congruential generator)
# ---------------------------------------------------------------------------

LCG_MULT = 0x41C64E6D
LCG_ADD = 0x00006073


def lcg_next(seed: int) -> int:
    """Advance the Gen 3 LCG one step, returning the new 32-bit seed."""
    return (seed * LCG_MULT + LCG_ADD) & U32


# Modular inverse of the multiplier, for stepping the LCG backwards.
_LCG_MULT_INV = pow(LCG_MULT, -1, 1 << 32)


def lcg_prev(seed: int) -> int:
    """Step the Gen 3 LCG one step **backwards** (inverse of :func:`lcg_next`)."""
    return ((seed - LCG_ADD) * _LCG_MULT_INV) & U32


def rewind(seed: int, n: int) -> int:
    """Step the LCG backwards ``n`` times.

    Used to convert a desired *generation-time* seed into the value to write
    into ``gRngValue`` ``n`` RNG-calls earlier (the fixed offset between a
    pre-generation save state and the PID roll).
    """
    for _ in range(n):
        seed = lcg_prev(seed)
    return seed


def advance(seed: int, n: int) -> int:
    """Step the LCG forwards ``n`` times (inverse of :func:`rewind`)."""
    for _ in range(n):
        seed = lcg_next(seed)
    return seed


def gen_method1(seed: int) -> tuple[int, Gen3IVs]:
    """Generate (PID, IVs) by Gen 3 **Method 1** starting from ``seed``.

    Four consecutive ``Random()`` calls, no gaps: PID low, PID high, then two
    15-bit IV words.  This is how FRLG rolls the starter (verified against
    LeafGreen: PID at RNG offset 90 from the written seed, IVs immediately
    after).
    """
    s = lcg_next(seed); pid_low = (s >> 16) & U16
    s = lcg_next(s); pid_high = (s >> 16) & U16
    pid = ((pid_high << 16) | pid_low) & U32
    s = lcg_next(s); iv1 = (s >> 16) & 0x7FFF
    s = lcg_next(s); iv2 = (s >> 16) & 0x7FFF
    ivs = Gen3IVs(
        hp=iv1 & 31, attack=(iv1 >> 5) & 31, defense=(iv1 >> 10) & 31,
        speed=iv2 & 31, sp_attack=(iv2 >> 5) & 31, sp_defense=(iv2 >> 10) & 31,
    )
    return pid, ivs


def rng16(seed: int) -> int:
    """The 16-bit value a Random() call yields: the high half of the
    *next* seed.  Returns just the 16-bit number (use :func:`lcg_next`
    yourself to keep the seed)."""
    return (lcg_next(seed) >> 16) & U16


class Gen3LCG:
    """Stateful Gen 3 LCG.  ``next16()`` mirrors the game's ``Random()``."""

    __slots__ = ("seed",)

    def __init__(self, seed: int) -> None:
        self.seed = seed & U32

    def advance(self, n: int = 1) -> int:
        for _ in range(n):
            self.seed = lcg_next(self.seed)
        return self.seed

    def next16(self) -> int:
        self.seed = lcg_next(self.seed)
        return (self.seed >> 16) & U16
