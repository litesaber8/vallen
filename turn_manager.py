"""
Vallen — Turn Manager.
Owns the turn flow and maps canonical actions to engine mutations.
"""

from typing import Any, Dict, Optional
import model
import engine
import interface

class TurnManager:
    def __init__(self):
        pass

    def resolve_card(self, state: model.GameState, card_id: str) -> model.Card:
        # Search in hand or field or support zones or resource pile to find the card with the given id
        for p in state.players:
            for c in p.hand:
                if c.id == card_id: return c
            for u in p.field_units():
                if u.card.id == card_id: return u.card
            for s in p.support_zones:
                if s and s.id == card_id: return s
            for rp in p.resource_pile:
                if rp.card.id == card_id: return rp.card
        raise ValueError(f"Card {card_id} not found in state")

    def resolve_unit(self, state: model.GameState, unit_id: str, player: Optional[model.Player] = None) -> model.UnitState:
        if player:
            for u in player.field_units():
                if u.uid == unit_id: return u
            raise ValueError(f"Unit {unit_id} not found on {player.name}'s field")

        for p in state.players:
            for u in p.field_units():
                if u.uid == unit_id: return u
        raise ValueError(f"Unit {unit_id} not found on any field")

    def _resolve_event(self, state: model.GameState):
        """
        Resolves the currently pending event.
        """
        event = state.pending_event
        if not event:
            return None

        action = event["action"]
        act_type = action.get("action")
        player = event["initiator"]

        state.emit(f"  Resolving pending {act_type}...")

        try:
            result = None
            if act_type == "attack":
                atk_id = action.get("attacker_id")
                def_id = action.get("defender_id")
                attacker = self.resolve_unit(state, atk_id, player)
                defender = self.resolve_unit(state, def_id) if def_id else None
                result = engine.resolve_battle(state, attacker, state.opponent, defender)
            elif act_type == "normal_support":
                card_id = action.get("card_id")
                card = self.resolve_card(state, card_id)
                target = action.get("target")
                if isinstance(target, str):
                    try:
                        target = self.resolve_unit(state, target)
                    except ValueError:
                        pass
                result = engine.do_normal_support(state, player, card, target)
            elif act_type == "equip_support":
                card_id = action.get("card_id")
                unit_id = action.get("unit_id")
                card = self.resolve_card(state, card_id)
                unit = self.resolve_unit(state, unit_id, player)
                result = engine.do_equip_support(state, player, card, unit)
            elif act_type == "field_support":
                card_id = action.get("card_id")
                card = self.resolve_card(state, card_id)
                result = engine.do_field_support(state, player, card)

            state.pending_event = None
            return result
        except (ValueError, model.InvariantError) as e:
            # Expected legality/invariant failures (missing target, mode
            # changed mid-window, etc.) cleanly terminate the pending event
            # rather than leaking it. Anything else (a genuine programming
            # error — AttributeError, TypeError, KeyError, ...) is NOT
            # caught here and propagates normally: we don't want a real bug
            # silently converted into a "fizzled" game event, and leaving
            # pending_event set in that case is correct — it's a crash, not
            # a legal game outcome.
            state.emit(f"  Event fails to resolve: {e}")
            state.pending_event = None
            return {"status": "fizzled", "error": str(e)}

    def validate_and_execute(self, state: model.GameState, action: Dict[str, Any]) -> Any:
        """
        The primary entry point for actions.
        Implements the Atomic Event Principle: Declare -> Respond -> Resolve.
        """
        act_type = action.get("action")
        player = state.active

        # 1. Handle response to a pending event
        if state.pending_event is not None:
            # The responder is the player who did NOT initiate the event
            responder = state.opponent if state.active == state.pending_event["initiator"] else state.active

            if act_type == "counter_support":
                card_id = action.get("card_id")
                card = self.resolve_card(state, card_id)

                # Validation: Is this counter legal?
                legal_counters = interface.legal_counters(state)
                if not any(c.id == card.id for c, e in legal_counters):
                    raise ValueError(f"Counter {card.name} is not legal for current event")

                # Execute Counter using the responder
                counter_res = engine.do_counter_support(state, responder, card, state.pending_event)
                state.emit(f"  {card.name} countered the event!")

                # Resolve original event (unless the counter cancels it)
                if counter_res:
                    state.emit("  Event cancelled by counter.")
                    state.pending_event = None
                    return {"status": "countered", "result": counter_res}

                return self._resolve_event(state)

            elif act_type == "pass_response":
                return self._resolve_event(state)

            else:
                raise ValueError("An event is pending. You must counter or pass.")

        # 2. Handle new action declarations
        # Determine if the action is Counterable
        is_counterable = act_type in ["attack", "normal_support", "equip_support", "field_support"]

        if is_counterable:
            # Create Pending Event
            if act_type == "attack":
                atk_id = action.get("attacker_id")
                def_id = action.get("defender_id")
                attacker = self.resolve_unit(state, atk_id, player)
                defender = self.resolve_unit(state, def_id) if def_id else None

                # Validate BEFORE declaring, same pattern as every other
                # action type below. A Defense Mode unit (or any other
                # illegal attacker/target pairing) must never be able to
                # set has_attacked or create a pending_event in the first
                # place -- illegal action -> ValueError -> zero mutation.
                legal_attacks = interface.legal_attacks(state)
                if not any(a is attacker and d is defender for a, d in legal_attacks):
                    raise ValueError(f"Attack by {attacker.card.name} is not legal right now")

                attacker.has_attacked = True

            state.pending_event = {
                "action": action,
                "initiator": player,
            }
            state.emit(f"  Declared {act_type}. Event is now PENDING.")
            return {"status": "pending", "event": state.pending_event}

        # 3. Resolve Non-Counterable Actions Immediately
        if act_type == "normal_summon":
            card_id = action.get("card_id")
            card = self.resolve_card(state, card_id)

            legal = interface.legal_normal_summons(player)
            valid_tribute = None
            for l_card, tributes in legal:
                if l_card.id == card.id:
                    valid_tribute = tributes[0]
                    break

            if valid_tribute is None:
                raise ValueError(f"Summon of {card.name} is not legal right now")

            return engine.do_normal_summon(state, player, card, valid_tribute)

        elif act_type == "level_up":
            unit_id = action.get("unit_id")
            card_id = action.get("card_id")
            unit = self.resolve_unit(state, unit_id, player)
            card = self.resolve_card(state, card_id)

            legal = interface.legal_level_ups(player)
            if not any(m.card.id == unit.card.id and c.id == card.id for m, c in legal):
                raise ValueError(f"Level-up of {unit.card.name} into {card.name} is not legal")

            return engine.do_level_up(state, player, unit, card)

        elif act_type == "switch_mode":
            unit_id = action.get("unit_id")
            unit = self.resolve_unit(state, unit_id, player)

            legal = interface.legal_mode_switches(player)
            if unit not in legal:
                raise ValueError(f"Mode switch for {unit.card.name} is not legal")

            engine.switch_mode(state, player, unit)
            return unit

        elif act_type == "end_phase":
            return "PHASE_END"

        else:
            raise ValueError(f"Unknown action type: {act_type}")

    def next_turn(self, state: model.GameState):
        """
        Handles the transition between players.
        """
        # 1. Recovery
        engine.recover_active_player_units(state)

        # 2. Switch Player
        state.active_idx = 1 - state.active_idx
        state.turn_number += 1

        # 3. New state setup (e.g. Draw phase)
        state.phase = model.Phase.DRAW

        # Simple hand limit check: if player has > 7 cards, they must discard.
        # For this minimalistic version, we'll just truncate.
        player = state.active
        player.unit_action_used_this_turn = False
        if len(player.hand) > 7:
            while len(player.hand) > 7:
                card = player.hand.pop()
                player.discard_pile.append(card)

        state.phase = model.Phase.MAIN

        return state
