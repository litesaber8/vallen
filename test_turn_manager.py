import model
import cards
import engine
from turn_manager import TurnManager

def test_turn_manager():
    # Setup
    user = model.Player(name="User", faction="Humanity", deck=[])
    ai = model.Player(name="AI", faction="Iron Recursion", deck=[])
    # Give user a card and some resources
    card = cards.CONSCRIPT # LV1, cost 0
    user.hand = [card]
    user.resource_pile = []

    state = model.GameState(players=(user, ai))
    tm = TurnManager()

    print("Testing Canonical Action: Normal Summon...")
    action = {"action": "normal_summon", "card_id": card.id}
    try:
        tm.validate_and_execute(state, action)
        print("SUCCESS: Summoned Conscript")
    except Exception as e:
        print(f"FAILED: {e}")

    print("\nTesting Canonical Action: Switch Mode...")
    unit = user.field_units()[0]
    action = {"action": "switch_mode", "unit_id": unit.card.id}
    try:
        tm.validate_and_execute(state, action)
        print(f"SUCCESS: Switched to {unit.mode.name}")
    except Exception as e:
        print(f"FAILED: {e}")

    print("\nTesting Canonical Action: Switch back to Attack...")
    try:
        tm.validate_and_execute(state, action)
        print(f"SUCCESS: Switched back to {unit.mode.name}")
    except Exception as e:
        print(f"FAILED: {e}")

    print("\nTesting Canonical Action: Attack Direct...")
    action = {"action": "attack", "attacker_id": unit.card.id, "defender_id": None}
    try:
        tm.validate_and_execute(state, action)
        print(f"SUCCESS: AI LP is now {ai.lp}")
    except Exception as e:
        print(f"FAILED: {e}")

    print("\nTesting Illegal Action: Attack again (should fail)...")
    try:
        tm.validate_and_execute(state, action)
        print("FAILED: Allowed attacking twice!")
    except Exception as e:
        print(f"SUCCESS: Blocked second attack: {e}")

    print("\nTesting Turn Transition...")
    tm.next_turn(state)
    print(f"Active player is now: {state.active.name}")

if __name__ == "__main__":
    test_turn_manager()
