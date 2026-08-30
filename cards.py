from model import Card, CardType

STATS = {
    1: (50, 100),
    2: (150, 250),
    3: (250, 400),
    4: (350, 550),
    5: (450, 650),
    6: (550, 750),
}


def unit(id_, name, faction, level, abilities=()):
    ap, hp = STATS[level]
    return Card(id=id_, name=name, faction=faction, card_type=CardType.UNIT,
                level=level, base_ap=ap, base_hp=hp, abilities=tuple(abilities))


# --- Humanity ---
CONSCRIPT = unit("h1", "Conscript", "Humanity", 1)
VETERAN_A = unit("h2a", "Veteran Footsoldier", "Humanity", 2)
VETERAN_B = unit("h2b", "Veteran Footsoldier", "Humanity", 2)
RENNE = unit("h3", "Field Medic Renne", "Humanity", 3)
RIFLE_SQUAD = unit("h2c", "Rifle Squad", "Humanity", 2)
COMBAT_ENGINEER = unit("h3b", "Combat Engineer", "Humanity", 3)

# --- Verdant ---
CREEPING_VINE_A = unit("v1a", "Creeping Vine", "Verdant", 1, abilities=["on_destruction_free_summon"])
CREEPING_VINE_B = unit("v1b", "Creeping Vine", "Verdant", 1, abilities=["on_destruction_free_summon"])
SPORE_CLOUD = unit("v2", "Spore Cloud", "Verdant", 2)
PACK_ALPHA = unit("v3", "Pack Alpha", "Verdant", 3)
ROOTWALKER = unit("v3b", "Ancient Rootwalker", "Verdant", 3, abilities=["prefers_defense"])
BRAMBLE_WARDEN = unit("v2b", "Bramble Warden", "Verdant", 2)

# --- Iron Recursion ---
SCOUT_MK1 = unit("i1", "Scout Unit MK.1", "Iron Recursion", 1,
                  abilities=["on_destruction_reclaim_discard"])
ANALYSIS_DRONE = unit("i2", "Analysis Drone", "Iron Recursion", 2)
TACTICAL_ENGINE_VOSS = unit("i3", "Tactical Engine Voss", "Iron Recursion", 3)
RECLAIMER_UNIT = unit("i3b", "Reclaimer Unit", "Iron Recursion", 3)
SIEGE_ARCHITECT = unit("i4", "Siege Architect", "Iron Recursion", 4)
SOVEREIGN_KAEL = unit("i5", "Sovereign Kael", "Iron Recursion", 5)

# --- Fallen Holy ---
LESSER_SERAPH = unit("f1", "Lesser Seraph", "Fallen Holy", 1)
DIVINE_ENFORCER = unit("f2", "Divine Enforcer", "Fallen Holy", 2)
INQUISITOR_VALE = unit("f3", "Inquisitor Vale", "Fallen Holy", 3, abilities=["deny_counter"])
THRONE_GUARDIAN = unit("f4", "Throne Guardian", "Fallen Holy", 4, abilities=["sacrifice_denial"])
FALLEN_SERAPH = unit("f5", "The Fallen Seraph", "Fallen Holy", 5)
