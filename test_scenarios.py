"""
Targeted mechanic tests — NOT full games.

Covers:
  (1) Iron Recursion's Discard -> Resource reclaim
  (2) Fallen Holy's sacrifice_denial (positive and negative cases)
  (3) Defense Mode mandatory taunt (with no-mutation assertions)
  (4) ResourcePileCard.value always == 1
"""

from model import Player, GameState, UnitState, Mode, ResourcePileCard, InvariantError
import engine
import heuristic
import cards


def test_iron_recursion_reclaim():
    print("=== TEST: Iron Recursion Discard -> Resource reclaim ===")
    ir = Player(name="Iron Recursion", faction="Iron Recursion", deck=[])
    fh = Player(name="Fallen Holy", faction="Fallen Holy", deck=[])
    state = GameState(players=(fh, ir), active_idx=0)

    ir.discard_pile.append(cards.ANALYSIS_DRONE)
    print(f"  Pre-state: IR Discard = {[c.name for c in ir.discard_pile]}, "
          f"IR Resource = {[c.card.name for c in ir.resource_pile]}")

    scout = UnitState(card=cards.SCOUT_MK1, owner=ir, current_hp=1, mode=Mode.ATTACK)
    ir.unit_zones[0] = scout
    attacker = UnitState(card=cards.LESSER_SERAPH, owner=fh,
                         current_hp=cards.LESSER_SERAPH.base_hp, mode=Mode.ATTACK)
    fh.unit_zones[0] = attacker

    destroyed = engine.resolve_battle(state, attacker, ir, defender=scout)
    assert scout.card in [c for _, c in destroyed], "Scout MK.1 should have been destroyed"

    for owner, destroyed_card in destroyed:
        if "on_destruction_reclaim_discard" in destroyed_card.abilities:
            choice = heuristic.choose_reclaim_from_discard(owner)
            assert choice is not None, "Heuristic should find Analysis Drone in Discard"
            engine.do_reclaim_from_discard(state, owner, choice)

    print(f"  Post-state: IR Discard = {[c.name for c in ir.discard_pile]}, "
          f"IR Resource = {[c.card.name for c in ir.resource_pile]}")
    assert cards.ANALYSIS_DRONE not in ir.discard_pile
    assert any(rc.card == cards.ANALYSIS_DRONE for rc in ir.resource_pile)
    print("  PASS: Analysis Drone moved Discard -> Resource Pile via On Destruction reclaim.\n")


def test_fallen_holy_sacrifice_denial():
    print("=== TEST: Fallen Holy sacrifice_denial (positive AND negative case) ===")
    fh = Player(name="Fallen Holy", faction="Fallen Holy", deck=[])
    ir = Player(name="Iron Recursion", faction="Iron Recursion", deck=[])
    state = GameState(players=(ir, fh), active_idx=0)

    guardian = UnitState(card=cards.THRONE_GUARDIAN, owner=fh, current_hp=10, mode=Mode.ATTACK)
    ally = UnitState(card=cards.LESSER_SERAPH, owner=fh, current_hp=50, mode=Mode.ATTACK)
    fh.unit_zones[0] = guardian
    fh.unit_zones[1] = ally
    striker = UnitState(card=cards.SOVEREIGN_KAEL, owner=ir,
                        current_hp=cards.SOVEREIGN_KAEL.base_hp, mode=Mode.ATTACK)
    ir.unit_zones[0] = striker

    destroyed = engine.resolve_battle(state, striker, fh, defender=guardian)
    print(f"  Case A (ally present): Guardian HP after lethal hit = {guardian.current_hp}, "
          f"still on field = {guardian in fh.field_units()}")
    assert guardian in fh.field_units(), "Guardian should NOT be destroyed while an ally is on field"
    assert (fh, cards.THRONE_GUARDIAN) not in destroyed
    print("  PASS: sacrifice_denial correctly prevented destruction with an ally present.\n")

    fh.unit_zones[1] = None
    guardian.current_hp = 10
    striker2 = UnitState(card=cards.SOVEREIGN_KAEL, owner=ir,
                         current_hp=cards.SOVEREIGN_KAEL.base_hp, mode=Mode.ATTACK)
    ir.unit_zones[0] = striker2
    destroyed2 = engine.resolve_battle(state, striker2, fh, defender=guardian)
    print(f"  Case B (no ally): still on field = {guardian in fh.field_units()}, "
          f"destroyed list = {[c.name for _, c in destroyed2]}")
    assert guardian not in fh.field_units(), "Guardian SHOULD be destroyed with no ally present"
    assert (fh, cards.THRONE_GUARDIAN) in destroyed2
    print("  PASS: sacrifice_denial correctly stopped applying once the ally was gone.\n")


def test_defense_mode_taunt():
    print("=== TEST: Defense Mode mandatory taunt (no mutation on illegal) ===")

    def snapshot(player):
        return {
            "lp": player.lp,
            "zones": [
                (u.card.id, u.current_hp, u.mode) if u else None
                for u in player.unit_zones
            ],
            "resource": [rc.card.id for rc in player.resource_pile],
            "discard": [c.id for c in player.discard_pile],
        }

    p1 = Player(name="Attacker", faction="Humanity", deck=[])
    p2 = Player(name="Defender", faction="Verdant", deck=[])
    state = GameState(players=(p1, p2), active_idx=0)

    atk = UnitState(card=cards.CONSCRIPT, owner=p1, current_hp=100, mode=Mode.ATTACK)
    p1.unit_zones[0] = atk

    engine.resolve_battle(state, atk, p2, defender=None)
    print("  PASS: direct attack when board empty")

    enemy_atk = UnitState(card=cards.CREEPING_VINE_A, owner=p2,
                          current_hp=100, mode=Mode.ATTACK)
    p2.unit_zones[0] = enemy_atk

    before = (snapshot(p1), snapshot(p2))
    try:
        engine.resolve_battle(state, atk, p2, defender=None)
        assert False, "should have raised"
    except InvariantError:
        assert (snapshot(p1), snapshot(p2)) == before
        print("  PASS: cannot direct-attack while units present (state unchanged)")

    engine.resolve_battle(state, atk, p2, defender=enemy_atk)
    print("  PASS: can attack the sole Attack-mode unit")

    p2.unit_zones = [None, None, None]
    enemy_def = UnitState(card=cards.ROOTWALKER, owner=p2,
                          current_hp=400, mode=Mode.DEFENSE)
    enemy_atk2 = UnitState(card=cards.CREEPING_VINE_A, owner=p2,
                           current_hp=100, mode=Mode.ATTACK)
    p2.unit_zones[0] = enemy_def
    p2.unit_zones[1] = enemy_atk2

    before = (snapshot(p1), snapshot(p2))
    try:
        engine.resolve_battle(state, atk, p2, defender=enemy_atk2)
        assert False, "should have raised"
    except InvariantError as e:
        assert "Defense Mode" in str(e) or "taunt" in str(e).lower()
        assert (snapshot(p1), snapshot(p2)) == before
        print("  PASS: cannot skip taunt (state unchanged)")

    before = (snapshot(p1), snapshot(p2))
    try:
        engine.resolve_battle(state, atk, p2, defender=None)
        assert False, "should have raised"
    except InvariantError:
        assert (snapshot(p1), snapshot(p2)) == before
        print("  PASS: cannot direct-attack while Defense unit present (state unchanged)")

    engine.resolve_battle(state, atk, p2, defender=enemy_def)
    print("  PASS: can attack the Defense-mode unit")

    atk.mode = Mode.DEFENSE
    before = (snapshot(p1), snapshot(p2))
    try:
        engine.resolve_battle(state, atk, p2, defender=enemy_def)
        assert False, "should have raised"
    except InvariantError:
        assert (snapshot(p1), snapshot(p2)) == before
        print("  PASS: Defense-mode unit cannot initiate attacks (state unchanged)")

    atk.mode = Mode.ATTACK
    p1.unit_zones[0] = None
    before = (snapshot(p1), snapshot(p2))
    try:
        engine.resolve_battle(state, atk, p2, defender=enemy_def)
        assert False, "should have raised"
    except InvariantError:
        assert (snapshot(p1), snapshot(p2)) == before
        print("  PASS: attacker must be on active player's field (state unchanged)")

    print("ALL DEFENSE-MODE TAUNT TESTS PASSED\n")


def test_resource_pile_tribute_value():
    print("=== TEST: Resource Pile cards always contribute value 1 ===")
    high = ResourcePileCard(card=cards.SOVEREIGN_KAEL)
    low  = ResourcePileCard(card=cards.CONSCRIPT)
    assert high.value == 1
    assert low.value == 1
    print("  PASS: ResourcePileCard.value is always 1\n")


if __name__ == "__main__":
    try:
        test_iron_recursion_reclaim()
        test_fallen_holy_sacrifice_denial()
        test_defense_mode_taunt()
        test_resource_pile_tribute_value()
        print("ALL TARGETED SCENARIO TESTS PASSED")
    except (AssertionError, InvariantError) as e:
        print(f"SCENARIO TEST FAILURE: {e}")
        raise
