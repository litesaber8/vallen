import random
import model
import engine
import interface
import cards

def get_all_cards():
    # Extract all Card objects from cards.py
    all_cards = []
    for attr in dir(cards):
        val = getattr(cards, attr)
        if isinstance(val, model.Card):
            all_cards.append(val)
    return all_cards

def print_state(state):
    print("\n" + "="*40)
    print(f" TURN {state.turn_number} | Phase: {state.phase.name}")
    print("="*40)

    for i, p in enumerate(state.players):
        role = "ACTIVE" if i == state.active_idx else "OPPONENT"
        print(f"[{role}] {p.name} | LP: {p.lp}")

        # Field
        field_str = " | ".join([
            (f"{u.card.name}({u.ap}/{u.current_hp})[{u.mode.name}]" if u else "EMPTY")
            for u in p.unit_zones
        ])
        print(f"  Field: [{field_str}]")

        # Hand
        if i == state.active_idx or p.name == "User":
            hand_str = ", ".join([c.name for c in p.hand])
            print(f"  Hand: {hand_str if hand_str else 'Empty'}")
        else:
            print(f"  Hand: {'*' * (len(p.hand) * 3)}")
    print("="*40)

def user_turn(state):
    player = state.active
    while True:
        print("\nYour Turn!")
        print("Actions: (S)ummon, (A)ttack, (M)ode Switch, (E)nd Turn")
        choice = input("Choose action: ").strip().upper()

        if choice == 'S':
            summons = interface.legal_normal_summons(player)
            if not summons:
                print("No legal summons available!")
                continue

            print("\nAvailable Summons:")
            for idx, (card, tributes) in enumerate(summons):
                print(f"{idx}: {card.name} (LV{card.level}, AP:{card.ap}, HP:{card.base_hp})")

            try:
                c_idx = int(input("Select card index: "))
                card, tributes_list = summons[c_idx]
                # For simplicity, pick the first legal tribute combination
                tribute = tributes_list[0]
                engine.do_normal_summon(state, player, card, tribute)
                print(f"Summoned {card.name}!")
            except (ValueError, IndexError):
                print("Invalid selection!")

        elif choice == 'A':
            attacks = interface.legal_attacks(state)
            if not attacks:
                print("No legal attacks available!")
                continue

            print("\nAvailable Attacks:")
            for idx, (atk, dfn) in enumerate(attacks):
                dfn_name = dfn.card.name if dfn else "Direct Attack"
                print(f"{idx}: {atk.card.name} -> {dfn_name}")

            try:
                a_idx = int(input("Select attack index: "))
                atk, dfn = attacks[a_idx]
                engine.resolve_battle(state, atk, state.opponent, dfn)
                print("Battle resolved!")
            except (ValueError, IndexError):
                print("Invalid selection!")

        elif choice == 'M':
            switches = interface.legal_mode_switches(player)
            if not switches:
                print("No units available to switch mode!")
                continue

            print("\nAvailable Mode Switches:")
            for idx, unit in enumerate(switches):
                print(f"{idx}: {unit.card.name} ({unit.mode.name} -> {'DEFENSE' if unit.mode == model.Mode.ATTACK else 'ATTACK'})")

            try:
                m_idx = int(input("Select unit index: "))
                unit = switches[m_idx]
                engine.switch_mode(state, player, unit)
                print(f"Switched {unit.card.name} mode!")
            except (ValueError, IndexError):
                print("Invalid selection!")

        elif choice == 'E':
            break
        else:
            print("Invalid choice!")

def ai_turn(state):
    player = state.active
    print(f"\nAI ({player.name}) is thinking...")

    # AI Heuristic
    while True:
        # 1. Attack Direct if possible
        attacks = interface.legal_attacks(state)
        direct_attacks = [a for a in attacks if a[1] is None]
        if direct_attacks:
            atk, dfn = direct_attacks[0]
            engine.resolve_battle(state, atk, state.opponent, dfn)
            print(f"AI attacks directly with {atk.card.name}!")
            continue

        # 2. Summon high AP card
        summons = interface.legal_normal_summons(player)
        if summons:
            # Pick card with highest AP
            best_summon = max(summons, key=lambda x: x[0].base_ap)
            card, tributes_list = best_summon
            tribute = tributes_list[0]
            engine.do_normal_summon(state, player, card, tribute)
            print(f"AI summons {card.name}!")
            continue

        # 3. Attack unit with lowest HP
        if attacks:
            # Filter for non-direct attacks
            unit_attacks = [a for a in attacks if a[1] is not None]
            if unit_attacks:
                # Target unit with lowest HP
                best_atk = min(unit_attacks, key=lambda x: x[1].current_hp)
                atk, dfn = best_atk
                engine.resolve_battle(state, atk, state.opponent, dfn)
                print(f"AI attacks {dfn.card.name} with {atk.card.name}!")
                continue

        # 4. Switch mode if needed (just switch first attack unit to defense for variety)
        switches = interface.legal_mode_switches(player)
        if switches:
            unit = switches[0]
            engine.switch_mode(state, player, unit)
            print(f"AI switches {unit.card.name} to {unit.mode.name}!")
            # We don't 'continue' here to avoid infinite mode switching loops

        break

def main():
    all_cards = get_all_cards()
    if not all_cards:
        print("No cards found in cards.py!")
        return

    user = model.Player(name="User", faction="Humanity", deck=[])
    ai = model.Player(name="AI", faction="Iron Recursion", deck=[])

    # Random hand of 5
    user.hand = random.sample(all_cards, 5)
    ai.hand = random.sample(all_cards, 5)

    # Initialize with some resources for easy summoning
    # In a real game, we'd have a deck/draw, but for minimalistic AI battle:
    for p in (user, ai):
        # Add some basic cards to resource pile so LV2+ can be summoned
        p.resource_pile = [model.ResourcePileCard(card=random.choice(all_cards)) for _ in range(5)]

    state = model.GameState(players=(user, ai))

    print("Welcome to the Vallen Minimalistic Battle!")

    while True:
        print_state(state)

        # Check win condition
        if user.lp <= 0:
            print("\nGAME OVER! AI Wins!")
            break
        if ai.lp <= 0:
            print("\nGAME OVER! User Wins!")
            break

        current_player = state.active
        if current_player.name == "User":
            user_turn(state)
        else:
            ai_turn(state)

        # End turn logic
        engine.recover_active_player_units(state)
        state.active_idx = 1 - state.active_idx
        state.turn_number += 1

if __name__ == "__main__":
    main()
