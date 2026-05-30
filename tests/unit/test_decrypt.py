"""Gen-3 box-mon decryption: decrypt_block round-trip + IV-word decode."""
import pytest

from pokemon_agent.shiny_gen3 import (
    SUBSTRUCT_SIZE,
    SUBSTRUCTURE_ORDER,
    decode_ivs,
    decrypt_block,
    ivs_from_decrypted,
)

U32 = 0xFFFFFFFF


def _encrypt(canonical: bytes, pid: int, otid: int) -> bytes:
    """Inverse of decrypt_block: permute canonical (G,A,E,M) into stored order
    (pid%24) then XOR each 32-bit word with pid^otid. Used only by these tests."""
    order = SUBSTRUCTURE_ORDER[pid % 24]
    stored = bytearray(48)
    for stored_idx, letter in enumerate(order):
        src = "GAEM".index(letter)
        stored[stored_idx * SUBSTRUCT_SIZE:(stored_idx + 1) * SUBSTRUCT_SIZE] = \
            canonical[src * SUBSTRUCT_SIZE:(src + 1) * SUBSTRUCT_SIZE]
    key = (pid ^ otid) & U32
    out = bytearray(48)
    for i in range(0, 48, 4):
        word = int.from_bytes(stored[i:i + 4], "little")
        out[i:i + 4] = ((word ^ key) & U32).to_bytes(4, "little")
    return bytes(out)


# Cover several pid%24 permutations + key patterns.
CASES = [
    (0x12345678, 0x8E6EC8B0),
    (0x00000000, 0x00000000),
    (0xFFFFFFFF, 0x12345678),
    (0x6AB32C6D, 0x8E6EC8B0),
    (0x000000017, 0xDEADBEEF),
]


@pytest.mark.parametrize("pid,otid", CASES)
def test_decrypt_inverts_encrypt(pid, otid):
    canonical = bytes((i * 7 + 3) & 0xFF for i in range(48))
    enc = _encrypt(canonical, pid, otid)
    assert decrypt_block(enc, pid, otid) == canonical


@pytest.mark.parametrize("pid,otid", CASES)
@pytest.mark.parametrize("ivword", [0x00000000, 0xFFFFFFFF, 0x7FBE_FA31 & 0x3FFFFFFF])
def test_iv_word_decode_roundtrip(pid, otid, ivword):
    # Build a canonical block whose Misc IV word (substruct 3, offset +4) is ivword.
    canonical = bytearray(48)
    misc_off = 3 * SUBSTRUCT_SIZE
    canonical[misc_off + 4:misc_off + 8] = (ivword & U32).to_bytes(4, "little")
    enc = _encrypt(bytes(canonical), pid, otid)
    dec = decrypt_block(enc, pid, otid)
    got = ivs_from_decrypted(dec)
    assert got.as_tuple() == decode_ivs(ivword).as_tuple()


def test_decode_ivs_bit_layout():
    # HP:0-4 Atk:5-9 Def:10-14 Spe:15-19 SpA:20-24 SpD:25-29
    word = 1 | (2 << 5) | (3 << 10) | (4 << 15) | (5 << 20) | (6 << 25)
    iv = decode_ivs(word)
    assert iv.as_tuple() == (1, 2, 3, 4, 5, 6)
