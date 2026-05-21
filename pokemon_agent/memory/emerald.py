"""Pokemon Emerald (USA) memory reader.

This reader targets the retail English Emerald ROM layout documented by the
pret/pokeemerald decompilation project. Emerald keeps most long-lived game
state behind SaveBlock pointers in EWRAM, and party Pokemon use the Gen 3
encrypted substructure format.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pokemon_agent.memory.reader import GameMemoryReader

# EWRAM globals (Pokemon Emerald, English retail)
ADDR_SAVEBLOCK1_PTR = 0x03005D8C
ADDR_SAVEBLOCK2_PTR = 0x03005D90

# SaveBlock1 offsets, from struct SaveBlock1 in pret/pokeemerald.
OFF_POS_X = 0x0000
OFF_POS_Y = 0x0002
OFF_LOCATION = 0x0004
OFF_PARTY_COUNT = 0x0234
OFF_PARTY_DATA = 0x0238
OFF_MONEY = 0x0490
OFF_BAG_ITEMS = 0x0560
OFF_BAG_KEY_ITEMS = 0x05D8
OFF_BAG_POKE_BALLS = 0x0650
OFF_FLAGS = 0x1270
OFF_VARS = 0x139C

# SaveBlock2 offsets.
OFF_PLAYER_NAME = 0x0000
OFF_PLAYER_GENDER = 0x0008
OFF_TRAINER_ID = 0x000A
OFF_PLAYTIME_H = 0x000E
OFF_PLAYTIME_M = 0x0010
OFF_PLAYTIME_S = 0x0011
OFF_POKEDEX = 0x0018
OFF_DEX_OWNED = OFF_POKEDEX + 0x10
OFF_DEX_SEEN = OFF_POKEDEX + 0x44
OFF_ENCRYPTION_KEY = 0x00AC

PARTY_MON_SIZE = 100
BOX_MON_SIZE = 80
POKEMON_NAME_LENGTH = 10
PLAYER_NAME_LENGTH = 7

VARS_START = 0x4000
SYSTEM_FLAGS = 0x860
FLAG_SYS_POKEMON_GET = SYSTEM_FLAGS + 0x0
FLAG_SYS_POKEDEX_GET = SYSTEM_FLAGS + 0x1
FLAG_SYS_POKENAV_GET = SYSTEM_FLAGS + 0x2
FLAG_SYS_GAME_CLEAR = SYSTEM_FLAGS + 0x4
FLAG_BADGE01_GET = SYSTEM_FLAGS + 0x7
FLAG_BADGE08_GET = SYSTEM_FLAGS + 0xE

FLAG_RECEIVED_HM_STRENGTH = 0x6A
FLAG_RECEIVED_HM_ROCK_SMASH = 0x6B
FLAG_RECEIVED_HM_FLASH = 0x6D
FLAG_RECEIVED_HM_FLY = 0x6E
FLAG_ADVENTURE_STARTED = 0x74
FLAG_RECEIVED_HM_SURF = 0x7A
FLAG_RECEIVED_HM_DIVE = 0x7B
FLAG_RECEIVED_HM_CUT = 0x89
FLAG_RECEIVED_HM_WATERFALL = 0x138
FLAG_ENTERED_ELITE_FOUR = 0x107

VAR_LITTLEROOT_RIVAL_STATE = 0x408D
VAR_BIRCH_LAB_STATE = 0x4084
VAR_ROUTE101_STATE = 0x4060
VAR_PETALBURG_CITY_STATE = 0x4057
VAR_PETALBURG_GYM_STATE = 0x4085
VAR_RUSTBORO_CITY_STATE = 0x405A
VAR_BOARD_BRINEY_BOAT_STATE = 0x408E
VAR_ROUTE110_STATE = 0x4069
VAR_SLATEPORT_OUTSIDE_MUSEUM_STATE = 0x40D2
VAR_WEATHER_INSTITUTE_STATE = 0x40B3
VAR_ELITE_4_STATE = 0x409C
VAR_SOOTOPOLIS_CITY_STATE = 0x405E

BADGE_NAMES = [
    "Stone",
    "Knuckle",
    "Dynamo",
    "Heat",
    "Balance",
    "Feather",
    "Mind",
    "Rain",
]

HM_FLAGS = {
    "Cut": FLAG_RECEIVED_HM_CUT,
    "Flash": FLAG_RECEIVED_HM_FLASH,
    "Rock Smash": FLAG_RECEIVED_HM_ROCK_SMASH,
    "Strength": FLAG_RECEIVED_HM_STRENGTH,
    "Surf": FLAG_RECEIVED_HM_SURF,
    "Fly": FLAG_RECEIVED_HM_FLY,
    "Dive": FLAG_RECEIVED_HM_DIVE,
    "Waterfall": FLAG_RECEIVED_HM_WATERFALL,
}

STORY_VARS = {
    "littleroot_rival_state": VAR_LITTLEROOT_RIVAL_STATE,
    "birch_lab_state": VAR_BIRCH_LAB_STATE,
    "route101_state": VAR_ROUTE101_STATE,
    "petalburg_city_state": VAR_PETALBURG_CITY_STATE,
    "petalburg_gym_state": VAR_PETALBURG_GYM_STATE,
    "rustboro_city_state": VAR_RUSTBORO_CITY_STATE,
    "board_briney_boat_state": VAR_BOARD_BRINEY_BOAT_STATE,
    "route110_state": VAR_ROUTE110_STATE,
    "slateport_outside_museum_state": VAR_SLATEPORT_OUTSIDE_MUSEUM_STATE,
    "weather_institute_state": VAR_WEATHER_INSTITUTE_STATE,
    "sootopolis_city_state": VAR_SOOTOPOLIS_CITY_STATE,
    "elite_4_state": VAR_ELITE_4_STATE,
}

SUBSTRUCTURE_ORDER = [
    "GAEM",
    "GAME",
    "GEAM",
    "GEMA",
    "GMAE",
    "GMEA",
    "AGEM",
    "AGME",
    "AEGM",
    "AEMG",
    "AMGE",
    "AMEG",
    "EGAM",
    "EGMA",
    "EAGM",
    "EAMG",
    "EMGA",
    "EMAG",
    "MGAE",
    "MGEA",
    "MAGE",
    "MAEG",
    "MEGA",
    "MEAG",
]

SPECIES_NAMES = {
    1: "Bulbasaur",
    2: "Ivysaur",
    3: "Venusaur",
    4: "Charmander",
    5: "Charmeleon",
    6: "Charizard",
    7: "Squirtle",
    8: "Wartortle",
    9: "Blastoise",
    10: "Caterpie",
    11: "Metapod",
    12: "Butterfree",
    13: "Weedle",
    14: "Kakuna",
    15: "Beedrill",
    16: "Pidgey",
    17: "Pidgeotto",
    18: "Pidgeot",
    19: "Rattata",
    20: "Raticate",
    21: "Spearow",
    22: "Fearow",
    23: "Ekans",
    24: "Arbok",
    25: "Pikachu",
    26: "Raichu",
    27: "Sandshrew",
    28: "Sandslash",
    29: "Nidoran♀",
    30: "Nidorina",
    31: "Nidoqueen",
    32: "Nidoran♂",
    33: "Nidorino",
    34: "Nidoking",
    35: "Clefairy",
    36: "Clefable",
    37: "Vulpix",
    38: "Ninetales",
    39: "Jigglypuff",
    40: "Wigglytuff",
    41: "Zubat",
    42: "Golbat",
    43: "Oddish",
    44: "Gloom",
    45: "Vileplume",
    46: "Paras",
    47: "Parasect",
    48: "Venonat",
    49: "Venomoth",
    50: "Diglett",
    51: "Dugtrio",
    52: "Meowth",
    53: "Persian",
    54: "Psyduck",
    55: "Golduck",
    56: "Mankey",
    57: "Primeape",
    58: "Growlithe",
    59: "Arcanine",
    60: "Poliwag",
    61: "Poliwhirl",
    62: "Poliwrath",
    63: "Abra",
    64: "Kadabra",
    65: "Alakazam",
    66: "Machop",
    67: "Machoke",
    68: "Machamp",
    69: "Bellsprout",
    70: "Weepinbell",
    71: "Victreebel",
    72: "Tentacool",
    73: "Tentacruel",
    74: "Geodude",
    75: "Graveler",
    76: "Golem",
    77: "Ponyta",
    78: "Rapidash",
    79: "Slowpoke",
    80: "Slowbro",
    81: "Magnemite",
    82: "Magneton",
    83: "Farfetch'd",
    84: "Doduo",
    85: "Dodrio",
    86: "Seel",
    87: "Dewgong",
    88: "Grimer",
    89: "Muk",
    90: "Shellder",
    91: "Cloyster",
    92: "Gastly",
    93: "Haunter",
    94: "Gengar",
    95: "Onix",
    96: "Drowzee",
    97: "Hypno",
    98: "Krabby",
    99: "Kingler",
    100: "Voltorb",
    101: "Electrode",
    102: "Exeggcute",
    103: "Exeggutor",
    104: "Cubone",
    105: "Marowak",
    106: "Hitmonlee",
    107: "Hitmonchan",
    108: "Lickitung",
    109: "Koffing",
    110: "Weezing",
    111: "Rhyhorn",
    112: "Rhydon",
    113: "Chansey",
    114: "Tangela",
    115: "Kangaskhan",
    116: "Horsea",
    117: "Seadra",
    118: "Goldeen",
    119: "Seaking",
    120: "Staryu",
    121: "Starmie",
    122: "Mr. Mime",
    123: "Scyther",
    124: "Jynx",
    125: "Electabuzz",
    126: "Magmar",
    127: "Pinsir",
    128: "Tauros",
    129: "Magikarp",
    130: "Gyarados",
    131: "Lapras",
    132: "Ditto",
    133: "Eevee",
    134: "Vaporeon",
    135: "Jolteon",
    136: "Flareon",
    137: "Porygon",
    138: "Omanyte",
    139: "Omastar",
    140: "Kabuto",
    141: "Kabutops",
    142: "Aerodactyl",
    143: "Snorlax",
    144: "Articuno",
    145: "Zapdos",
    146: "Moltres",
    147: "Dratini",
    148: "Dragonair",
    149: "Dragonite",
    150: "Mewtwo",
    151: "Mew",
    152: "Chikorita",
    153: "Bayleef",
    154: "Meganium",
    155: "Cyndaquil",
    156: "Quilava",
    157: "Typhlosion",
    158: "Totodile",
    159: "Croconaw",
    160: "Feraligatr",
    161: "Sentret",
    162: "Furret",
    163: "Hoothoot",
    164: "Noctowl",
    165: "Ledyba",
    166: "Ledian",
    167: "Spinarak",
    168: "Ariados",
    169: "Crobat",
    170: "Chinchou",
    171: "Lanturn",
    172: "Pichu",
    173: "Cleffa",
    174: "Igglybuff",
    175: "Togepi",
    176: "Togetic",
    177: "Natu",
    178: "Xatu",
    179: "Mareep",
    180: "Flaaffy",
    181: "Ampharos",
    182: "Bellossom",
    183: "Marill",
    184: "Azumarill",
    185: "Sudowoodo",
    186: "Politoed",
    187: "Hoppip",
    188: "Skiploom",
    189: "Jumpluff",
    190: "Aipom",
    191: "Sunkern",
    192: "Sunflora",
    193: "Yanma",
    194: "Wooper",
    195: "Quagsire",
    196: "Espeon",
    197: "Umbreon",
    198: "Murkrow",
    199: "Slowking",
    200: "Misdreavus",
    201: "Unown",
    202: "Wobbuffet",
    203: "Girafarig",
    204: "Pineco",
    205: "Forretress",
    206: "Dunsparce",
    207: "Gligar",
    208: "Steelix",
    209: "Snubbull",
    210: "Granbull",
    211: "Qwilfish",
    212: "Scizor",
    213: "Shuckle",
    214: "Heracross",
    215: "Sneasel",
    216: "Teddiursa",
    217: "Ursaring",
    218: "Slugma",
    219: "Magcargo",
    220: "Swinub",
    221: "Piloswine",
    222: "Corsola",
    223: "Remoraid",
    224: "Octillery",
    225: "Delibird",
    226: "Mantine",
    227: "Skarmory",
    228: "Houndour",
    229: "Houndoom",
    230: "Kingdra",
    231: "Phanpy",
    232: "Donphan",
    233: "Porygon2",
    234: "Stantler",
    235: "Smeargle",
    236: "Tyrogue",
    237: "Hitmontop",
    238: "Smoochum",
    239: "Elekid",
    240: "Magby",
    241: "Miltank",
    242: "Blissey",
    243: "Raikou",
    244: "Entei",
    245: "Suicune",
    246: "Larvitar",
    247: "Pupitar",
    248: "Tyranitar",
    249: "Lugia",
    250: "Ho-Oh",
    251: "Celebi",
    277: "Treecko",
    278: "Grovyle",
    279: "Sceptile",
    280: "Torchic",
    281: "Combusken",
    282: "Blaziken",
    283: "Mudkip",
    284: "Marshtomp",
    285: "Swampert",
    286: "Poochyena",
    287: "Mightyena",
    288: "Zigzagoon",
    289: "Linoone",
    290: "Wurmple",
    291: "Silcoon",
    292: "Beautifly",
    293: "Cascoon",
    294: "Dustox",
    295: "Lotad",
    296: "Lombre",
    297: "Ludicolo",
    298: "Seedot",
    299: "Nuzleaf",
    300: "Shiftry",
    301: "Nincada",
    302: "Ninjask",
    303: "Shedinja",
    304: "Taillow",
    305: "Swellow",
    306: "Shroomish",
    307: "Breloom",
    308: "Spinda",
    309: "Wingull",
    310: "Pelipper",
    311: "Surskit",
    312: "Masquerain",
    313: "Wailmer",
    314: "Wailord",
    315: "Skitty",
    316: "Delcatty",
    317: "Kecleon",
    318: "Baltoy",
    319: "Claydol",
    320: "Nosepass",
    321: "Torkoal",
    322: "Sableye",
    323: "Barboach",
    324: "Whiscash",
    325: "Luvdisc",
    326: "Corphish",
    327: "Crawdaunt",
    328: "Feebas",
    329: "Milotic",
    330: "Carvanha",
    331: "Sharpedo",
    332: "Trapinch",
    333: "Vibrava",
    334: "Flygon",
    335: "Makuhita",
    336: "Hariyama",
    337: "Electrike",
    338: "Manectric",
    339: "Numel",
    340: "Camerupt",
    341: "Spheal",
    342: "Sealeo",
    343: "Walrein",
    344: "Cacnea",
    345: "Cacturne",
    346: "Snorunt",
    347: "Glalie",
    348: "Lunatone",
    349: "Solrock",
    350: "Azurill",
    351: "Spoink",
    352: "Grumpig",
    353: "Plusle",
    354: "Minun",
    355: "Mawile",
    356: "Meditite",
    357: "Medicham",
    358: "Swablu",
    359: "Altaria",
    360: "Wynaut",
    361: "Duskull",
    362: "Dusclops",
    363: "Roselia",
    364: "Slakoth",
    365: "Vigoroth",
    366: "Slaking",
    367: "Gulpin",
    368: "Swalot",
    369: "Tropius",
    370: "Whismur",
    371: "Loudred",
    372: "Exploud",
    373: "Clamperl",
    374: "Huntail",
    375: "Gorebyss",
    376: "Absol",
    377: "Shuppet",
    378: "Banette",
    379: "Seviper",
    380: "Zangoose",
    381: "Relicanth",
    382: "Aron",
    383: "Lairon",
    384: "Aggron",
    385: "Castform",
    386: "Volbeat",
    387: "Illumise",
    388: "Lileep",
    389: "Cradily",
    390: "Anorith",
    391: "Armaldo",
    392: "Ralts",
    393: "Kirlia",
    394: "Gardevoir",
    395: "Bagon",
    396: "Shelgon",
    397: "Salamence",
    398: "Beldum",
    399: "Metang",
    400: "Metagross",
    401: "Regirock",
    402: "Regice",
    403: "Registeel",
    404: "Kyogre",
    405: "Groudon",
    406: "Rayquaza",
    407: "Latias",
    408: "Latios",
    409: "Jirachi",
    410: "Deoxys",
    411: "Chimecho",
}

MOVE_NAMES = {
    15: "Cut",
    33: "Tackle",
    45: "Growl",
    57: "Surf",
    70: "Strength",
    71: "Absorb",
    98: "Quick Attack",
    127: "Waterfall",
    148: "Flash",
    249: "Rock Smash",
    291: "Dive",
}

ITEM_NAMES = {
    1: "Master Ball",
    2: "Ultra Ball",
    3: "Great Ball",
    4: "Poke Ball",
    13: "Potion",
    19: "Full Restore",
    25: "Max Revive",
    259: "HM01",
    260: "HM02",
    261: "HM03",
    262: "HM04",
    263: "HM05",
    264: "HM06",
    265: "HM07",
    266: "HM08",
}

MAP_NAMES = {
    (0, 0): "Petalburg City",
    (0, 1): "Slateport City",
    (0, 2): "Mauville City",
    (0, 3): "Rustboro City",
    (0, 4): "Fortree City",
    (0, 5): "Lilycove City",
    (0, 6): "Mossdeep City",
    (0, 7): "Sootopolis City",
    (0, 8): "Ever Grande City",
    (0, 9): "Littleroot Town",
    (0, 10): "Oldale Town",
    (0, 11): "Dewford Town",
    (0, 12): "Lavaridge Town",
    (0, 13): "Fallarbor Town",
    (0, 14): "Verdanturf Town",
    (0, 15): "Pacifidlog Town",
}

FACING_NAMES = {1: "down", 2: "up", 3: "left", 4: "right"}


def _build_gen3_encoding() -> Dict[int, str]:
    table: Dict[int, str] = {0x00: " ", 0xAB: "!", 0xAD: ".", 0xB8: ","}
    for i, char in enumerate("0123456789"):
        table[0xA1 + i] = char
    for i, char in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        table[0xBB + i] = char
    for i, char in enumerate("abcdefghijklmnopqrstuvwxyz"):
        table[0xD5 + i] = char
    return table


GEN3_ENCODING = _build_gen3_encoding()


class EmeraldMemoryReader(GameMemoryReader):
    """Memory reader for Pokemon Emerald (USA)."""

    @property
    def game_name(self) -> str:
        return "Pokemon Emerald (USA)"

    def _get_saveblock1(self) -> int:
        return self.emu.read_u32(ADDR_SAVEBLOCK1_PTR)

    def _get_saveblock2(self) -> int:
        return self.emu.read_u32(ADDR_SAVEBLOCK2_PTR)

    def _decode_text(self, data: bytes) -> str:
        chars: List[str] = []
        for byte in data:
            if byte == 0xFF:
                break
            chars.append(GEN3_ENCODING.get(byte, "?"))
        return "".join(chars).strip()

    def _read_flag(self, flag_id: int) -> bool:
        sb1 = self._get_saveblock1()
        byte = self.emu.read_u8(sb1 + OFF_FLAGS + flag_id // 8)
        return bool(byte & (1 << (flag_id % 8)))

    def _read_var(self, var_id: int) -> int:
        if var_id < VARS_START:
            raise ValueError(f"Not a normal Emerald var id: 0x{var_id:04X}")
        return self.emu.read_u16(self._get_saveblock1() + OFF_VARS + (var_id - VARS_START) * 2)

    def _encryption_key(self) -> int:
        return self.emu.read_u32(self._get_saveblock2() + OFF_ENCRYPTION_KEY)

    def _decrypt_pokemon(self, addr: int) -> Dict[str, bytes | int | str]:
        raw = self.emu.read_range(addr, PARTY_MON_SIZE)
        personality = int.from_bytes(raw[0:4], "little")
        ot_id = int.from_bytes(raw[4:8], "little")
        key = personality ^ ot_id
        encrypted = raw[32:80]
        decrypted = bytearray()
        for i in range(0, len(encrypted), 4):
            word = int.from_bytes(encrypted[i : i + 4], "little") ^ key
            decrypted.extend(word.to_bytes(4, "little"))

        order = SUBSTRUCTURE_ORDER[personality % 24]
        parts = {name: bytes(decrypted[i * 12 : (i + 1) * 12]) for i, name in enumerate(order)}
        return {
            "raw": raw,
            "personality": personality,
            "ot_id": ot_id,
            "nickname": self._decode_text(raw[8 : 8 + POKEMON_NAME_LENGTH]),
            "G": parts["G"],
            "A": parts["A"],
            "E": parts["E"],
            "M": parts["M"],
        }

    def _read_pokemon(self, addr: int) -> Dict[str, Any]:
        mon = self._decrypt_pokemon(addr)
        raw = mon["raw"]
        growth = mon["G"]
        attacks = mon["A"]
        evs = mon["E"]
        misc = mon["M"]

        species_id = int.from_bytes(growth[0:2], "little")
        held_item_id = int.from_bytes(growth[2:4], "little")
        moves = []
        for i in range(4):
            move_id = int.from_bytes(attacks[i * 2 : i * 2 + 2], "little")
            if move_id:
                moves.append(
                    {
                        "id": move_id,
                        "name": MOVE_NAMES.get(move_id, f"Move {move_id}"),
                        "pp": attacks[8 + i],
                    }
                )

        iv_word = int.from_bytes(misc[4:8], "little")
        return {
            "species_id": species_id,
            "species": SPECIES_NAMES.get(species_id, f"Species {species_id}"),
            "nickname": mon["nickname"],
            "level": raw[84],
            "hp": int.from_bytes(raw[86:88], "little"),
            "max_hp": int.from_bytes(raw[88:90], "little"),
            "status": self._decode_status(int.from_bytes(raw[80:84], "little")),
            "held_item_id": held_item_id,
            "held_item": (
                ITEM_NAMES.get(held_item_id, f"Item {held_item_id}") if held_item_id else None
            ),
            "moves": moves,
            "stats": {
                "attack": int.from_bytes(raw[90:92], "little"),
                "defense": int.from_bytes(raw[92:94], "little"),
                "speed": int.from_bytes(raw[94:96], "little"),
                "sp_attack": int.from_bytes(raw[96:98], "little"),
                "sp_defense": int.from_bytes(raw[98:100], "little"),
            },
            "evs": {
                "hp": evs[0],
                "attack": evs[1],
                "defense": evs[2],
                "speed": evs[3],
                "sp_attack": evs[4],
                "sp_defense": evs[5],
            },
            "ivs": {
                "hp": iv_word & 0x1F,
                "attack": (iv_word >> 5) & 0x1F,
                "defense": (iv_word >> 10) & 0x1F,
                "speed": (iv_word >> 15) & 0x1F,
                "sp_attack": (iv_word >> 20) & 0x1F,
                "sp_defense": (iv_word >> 25) & 0x1F,
            },
            "ot_id": mon["ot_id"],
            "experience": int.from_bytes(growth[4:8], "little"),
        }

    def _decode_status(self, status: int) -> str:
        if status == 0:
            return "OK"
        parts = []
        sleep = status & 0x07
        if sleep:
            parts.append(f"SLP({sleep})")
        if status & 0x08:
            parts.append("PSN")
        if status & 0x10:
            parts.append("BRN")
        if status & 0x20:
            parts.append("FRZ")
        if status & 0x40:
            parts.append("PAR")
        if status & 0x80:
            parts.append("TOX")
        return "/".join(parts) if parts else f"0x{status:08X}"

    def read_player(self) -> Dict[str, Any]:
        sb1 = self._get_saveblock1()
        sb2 = self._get_saveblock2()
        badge_list = [
            BADGE_NAMES[i]
            for i in range(8)
            if self._read_flag(FLAG_BADGE01_GET + i)
        ]
        return {
            "name": self._decode_text(
                self.emu.read_range(sb2 + OFF_PLAYER_NAME, PLAYER_NAME_LENGTH + 1)
            ),
            "gender": {0: "male", 1: "female"}.get(
                self.emu.read_u8(sb2 + OFF_PLAYER_GENDER), "unknown"
            ),
            "trainer_id": self.emu.read_range(sb2 + OFF_TRAINER_ID, 4).hex(),
            "money": self.emu.read_u32(sb1 + OFF_MONEY) ^ self._encryption_key(),
            "badges": badge_list,
            "badge_count": len(badge_list),
            "position": {
                "x": self.emu.read_u16(sb1 + OFF_POS_X),
                "y": self.emu.read_u16(sb1 + OFF_POS_Y),
            },
            "facing": "unknown",
            "play_time": (
                f"{self.emu.read_u16(sb2 + OFF_PLAYTIME_H)}:"
                f"{self.emu.read_u8(sb2 + OFF_PLAYTIME_M):02d}:"
                f"{self.emu.read_u8(sb2 + OFF_PLAYTIME_S):02d}"
            ),
        }

    def read_party(self) -> List[Dict[str, Any]]:
        sb1 = self._get_saveblock1()
        count = min(self.emu.read_u8(sb1 + OFF_PARTY_COUNT), 6)
        return [
            self._read_pokemon(sb1 + OFF_PARTY_DATA + i * PARTY_MON_SIZE)
            for i in range(count)
        ]

    def read_bag(self) -> List[Dict[str, Any]]:
        pockets = [
            ("items", OFF_BAG_ITEMS, 30),
            ("key_items", OFF_BAG_KEY_ITEMS, 30),
            ("poke_balls", OFF_BAG_POKE_BALLS, 16),
        ]
        sb1 = self._get_saveblock1()
        bag: List[Dict[str, Any]] = []
        for pocket, offset, limit in pockets:
            for i in range(limit):
                item_id = self.emu.read_u16(sb1 + offset + i * 4)
                quantity = self.emu.read_u16(sb1 + offset + i * 4 + 2) ^ (
                    self._encryption_key() & 0xFFFF
                )
                if item_id == 0:
                    continue
                bag.append(
                    {
                        "pocket": pocket,
                        "id": item_id,
                        "item": ITEM_NAMES.get(item_id, f"Item {item_id}"),
                        "quantity": quantity,
                    }
                )
        return bag

    def read_battle(self) -> Dict[str, Any]:
        # A conservative placeholder: precise battle globals are not exposed
        # through SaveBlock state, so avoid guessing from stale battle structs.
        return {"in_battle": False, "type": "unknown"}

    def read_dialog(self) -> Dict[str, Any]:
        return {"active": False}

    def read_map_info(self) -> Dict[str, Any]:
        sb1 = self._get_saveblock1()
        map_group = self.emu.read_u8(sb1 + OFF_LOCATION)
        map_num = self.emu.read_u8(sb1 + OFF_LOCATION + 1)
        return {
            "map_group": map_group,
            "map_num": map_num,
            "map_id": (map_group << 8) | map_num,
            "map_name": MAP_NAMES.get((map_group, map_num), f"Map {map_group}.{map_num}"),
        }

    def read_flags(self) -> Dict[str, Any]:
        owned_bits = self.read_bits(self._get_saveblock2() + OFF_DEX_OWNED, 52)
        seen_bits = self.read_bits(self._get_saveblock2() + OFF_DEX_SEEN, 52)
        badge_list = [
            BADGE_NAMES[i]
            for i in range(8)
            if self._read_flag(FLAG_BADGE01_GET + i)
        ]
        return {
            "has_pokemon": self._read_flag(FLAG_SYS_POKEMON_GET),
            "has_pokedex": self._read_flag(FLAG_SYS_POKEDEX_GET),
            "has_pokenav": self._read_flag(FLAG_SYS_POKENAV_GET),
            "adventure_started": self._read_flag(FLAG_ADVENTURE_STARTED),
            "game_clear": self._read_flag(FLAG_SYS_GAME_CLEAR),
            "entered_elite_four": self._read_flag(FLAG_ENTERED_ELITE_FOUR),
            "badges": badge_list,
            "badge_count": len(badge_list),
            "hm_received": {
                name: self._read_flag(flag_id) for name, flag_id in HM_FLAGS.items()
            },
            "story_vars": {
                name: self._read_var(var_id) for name, var_id in STORY_VARS.items()
            },
            "pokedex_owned": sum(owned_bits[:386]),
            "pokedex_seen": sum(seen_bits[:386]),
        }


PokemonEmeraldReader = EmeraldMemoryReader
