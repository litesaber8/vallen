"""
Focused legality tests for Normal Support target enumeration (Pre-Phase 4A).

Proves:
- legal (card, target) pairs are enumerated
- illegal / non-Normal cards are excluded
- current fixture Normals are targetless (target=None)
- structure matches the Canonical Action expectation
"""

import model
import cards
import interface


def assert_equal(actual, expected, msg):
    if actual != expected:
        raise AssertionError(f"{msg} | Expected {expected!r}, got {actual!r}")


def setup_player(hand=None, field=None):
    p = model.Player(name="P1", faction="Humanity", deck=[])
    if hand is not None:
        p.hand = list(hand)
    if field is not None:
        for i, u in enumerate(field):
            p.unit_zones[i] = u
    return p


def test_empty_hand_yields_empty():
    print("T1: empty hand -> no Normal Supports")
    p = setup_player(hand=[])
    legal = interface.legal_normal_supports(p)
    assert_equal(legal, [], "Empty hand must yield empty list")


def test_non_normal_excluded():
    print("T2: Equip / Field / Unit / Counter excluded")
    p = setup_player(hand=[
        cards.S_EQUIP,
        cards.S_FIELD,
        cards.S_COUNTER,
        cards.CONSCRIPT,
    ])
    legal = interface.legal_normal_supports(p)
    assert_equal(legal, [], "Only SupportType.NORMAL may appear")


def test_normal_enumerated_with_none_target():
    print("T3: Normal Support appears exactly once with target=None")
    p = setup_player(hand=[cards.S_NORMAL])
    legal = interface.legal_normal_supports(p)
    assert_equal(len(legal), 1, "Exactly one pair expected")
    card, target = legal[0]
    assert_equal(card, cards.S_NORMAL, "Card must be the Normal Support")
    assert_equal(target, None, "Current fixture Normals are targetless")


def test_multiple_normals():
    print("T4: multiple identical Normals each appear once with target=None")
    # Two distinct card objects of the same definition
    n1 = cards.S_NORMAL
    n2 = model.Card(
        id="sn1b", name="Quick Strike", faction="Humanity",
        card_type=model.CardType.SUPPORT, level=0,
        support_type=model.SupportType.NORMAL,
    )
    p = setup_player(hand=[n1, n2, cards.CONSCRIPT])
    legal = interface.legal_normal_supports(p)
    assert_equal(len(legal), 2, "Both Normals must be enumerated")
    cards_seen = {c for c, t in legal}
    assert n1 in cards_seen and n2 in cards_seen
    for c, t in legal:
        assert_equal(t, None, "All current Normals are targetless")


def test_no_invented_unit_targets():
    print("T5: units on field are NOT auto-enumerated as targets")
    unit = model.UnitState(
        uid="u1", card=cards.CONSCRIPT, owner=None, current_hp=100
    )
    p = setup_player(hand=[cards.S_NORMAL], field=[unit])
    # Fix owner reference
    unit.owner = p
    legal = interface.legal_normal_supports(p)
    assert_equal(len(legal), 1, "Only the targetless entry")
    card, target = legal[0]
    assert_equal(card, cards.S_NORMAL, "Card identity")
    assert_equal(target, None, "Must not invent unit targets")


def test_return_type_shape():
    print("T6: every entry is (Card, Optional[UnitState])")
    p = setup_player(hand=[cards.S_NORMAL, cards.S_EQUIP])
    legal = interface.legal_normal_supports(p)
    for item in legal:
        assert isinstance(item, tuple) and len(item) == 2, "Must be 2-tuple"
        card, target = item
        assert isinstance(card, model.Card)
        assert target is None or isinstance(target, model.UnitState)


if __name__ == "__main__":
    try:
        test_empty_hand_yields_empty()
        test_non_normal_excluded()
        test_normal_enumerated_with_none_target()
        test_multiple_normals()
        test_no_invented_unit_targets()
        test_return_type_shape()
        print("\n==========================================")
        print("INTERFACE NORMAL SUPPORT: PASSED (T1-T6)")
        print("==========================================")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
