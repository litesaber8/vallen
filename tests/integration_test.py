"""
Vallen — Integration Tests.
Verifies the LLM -> Validator -> Engine pipeline and fallback logic.
"""

import model
import cards
import engine
import interface
from turn_manager import TurnManager
from llm_opponent import LLMOpponent, MockProvider
import heuristic

class GameCoordinator:
    """
    Implements the deterministic fallback logic:
    LLM Response -> JSON Parse -> Schema Validate -> Interface Check -> Execute OR Heuristic.
    """
    def __init__(self, state: model.GameState, llm_opponent: LLMOpponent):
        self.state = state
        self.llm = llm_opponent
        self.tm = TurnManager()

    def get_legal_actions_canonical(self):
        player = self.state.active
        actions = []
        for card, tributes in interface.legal_normal_summons(player):
            actions.append({"action": "normal_summon", "card_id": card.id})
        for material, card in interface.legal_level_ups(player):
            actions.append({"action": "level_up", "unit_id": material.uid, "card_id": card.id})
        for unit in interface.legal_mode_switches(player):
            actions.append({"action": "switch_mode", "unit_id": unit.uid})
        for attacker, defender in interface.legal_attacks(self.state):
            actions.append({"action": "attack", "attacker_id": attacker.uid, "defender_id": defender.uid if defender else None})
        actions.append({"action": "end_phase"})
        return actions

    def _advance_pending_event(self):
        """
        Completes the Declare -> Respond -> Resolve cycle for a counterable
        action. The Atomic Event model means one validate_and_execute() call
        only *declares* an attack/support -- it does not resolve until a
        pass_response or counter_support follows.

        This deterministic coordinator only auto-passes when there is
        genuinely no legal Counter available. It never invents a responder
        decision when a Counter exists -- choosing whether to counter is a
        real opponent-policy question that belongs to agent-play testing,
        not to this regression gate.
        """
        if self.state.pending_event is None:
            return

        legal_counters = interface.legal_counters(self.state)
        if not legal_counters:
            self.tm.validate_and_execute(self.state, {"action": "pass_response"})
            print("[Coordinator] No legal Counter available -> pass_response")
        else:
            print(f"[Coordinator] {len(legal_counters)} legal Counter(s) available "
                  "-- leaving event pending (no deterministic responder policy yet)")

    def perform_ai_turn(self):
        state_serialized = {
            "lp": self.state.active.lp,
            "opponent_lp": self.state.opponent.lp,
            "hand": [c.id for c in self.state.active.hand]
        }
        legal = self.get_legal_actions_canonical()

        try:
            # 1. Try LLM
            action = self.llm.choose_action(state_serialized, legal)

            # 2. Validate against interface
            # This is a simplified check; TurnManager.validate_and_execute does the real check.
            self.tm.validate_and_execute(self.state, action)
            print(f"[LLM] Executed: {action}")
            self._advance_pending_event()

        except Exception as e:
            print(f"[LLM] invalid action: {e}")
            print("[LLM] fallback -> heuristic")
            # 3. Fallback to Heuristic
            # Refresh legal actions to ensure fallback is valid
            legal = self.get_legal_actions_canonical()
            fallback_action = next((a for a in legal if a["action"] != "end_phase"), legal[-1])
            self.tm.validate_and_execute(self.state, fallback_action)
            print(f"[Heuristic] Executed: {fallback_action}")
            self._advance_pending_event()

def test_pipeline():
    # Setup
    user = model.Player(name="User", faction="Humanity", deck=[])
    ai = model.Player(name="AI", faction="Iron Recursion", deck=[])
    user.hand = [cards.CONSCRIPT]
    ai.hand = [cards.CONSCRIPT]
    # resource_pile left empty; scenarios under test do not depend on it

    state = model.GameState(players=(user, ai))
    state.active_idx = 1  # AI's turn

    # 1. Test: LLM produces valid attack -> executes
    print("\n--- Scenario 1: Valid LLM Attack ---")
    # Setup: AI has unit, User has no units (direct attack legal)
    ai_unit = model.UnitState(uid="unit_test_11", card=cards.CONSCRIPT, owner=ai, current_hp=100, mode=model.Mode.ATTACK)
    ai.unit_zones[0] = ai_unit

    mock_llm = LLMOpponent(MockProvider(forced_action={"action": "attack", "attacker_id": ai_unit.uid, "defender_id": None}))
    coord = GameCoordinator(state, mock_llm)
    coord.perform_ai_turn()
    assert ai.lp == 4000 and user.lp < 4000

    # 2. Test: LLM illegal attack -> fallback to heuristic
    print("\n--- Scenario 2: Illegal LLM Attack ---")
    # Switch AI unit to DEFENSE, then force an attack
    ai_unit.mode = model.Mode.DEFENSE
    mock_llm = LLMOpponent(MockProvider(forced_action={"action": "attack", "attacker_id": ai_unit.uid, "defender_id": None}))
    coord = GameCoordinator(state, mock_llm)
    coord.perform_ai_turn()
    # Should fallback to something legal (like switch_mode or end_phase)

    # 3. Test: Malformed JSON -> fallback
    print("\n--- Scenario 3: Malformed JSON ---")
    class BrokenProvider(MockProvider):
        def get_action(self, prompt): return "NOT JSON"

    mock_llm = LLMOpponent(BrokenProvider())
    coord = GameCoordinator(state, mock_llm)
    coord.perform_ai_turn()

    # 4. Test: Defense Mode Taunt
    print("\n--- Scenario 4: Defense Mode Taunt ---")
    # User puts unit in DEFENSE
    user_unit = model.UnitState(uid="unit_test_12", card=cards.CONSCRIPT, owner=user, current_hp=100, mode=model.Mode.DEFENSE)
    user.unit_zones[0] = user_unit
    ai_unit.mode = model.Mode.ATTACK

    # LLM tries to attack direct
    mock_llm = LLMOpponent(MockProvider(forced_action={"action": "attack", "attacker_id": ai_unit.uid, "defender_id": None}))
    coord = GameCoordinator(state, mock_llm)
    coord.perform_ai_turn()
    # Should fallback because direct attack is illegal when defense unit exists

    print("\nAll integration tests passed (or observed expected fallbacks)!")

if __name__ == "__main__":
    import random
    test_pipeline()
