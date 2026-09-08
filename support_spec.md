# Vallen: Support Card Specification v1.1 (LOCKED)

## I. The Atomic Event Principle
**All game actions follow a strict, linear sequence: Declare $\rightarrow$ Respond $\rightarrow$ Resolve.**

1.  **Declaration**: A player performs a legal action. The event is declared and becomes **Pending**.
2.  **Pending State**: A pending event **does not change the game state**. No HP is reduced, no units are moved, and no effects are applied until resolution.
3.  **Response Window**: If the event is "Counterable," the opposing player may activate **one** eligible Counter Support.
4.  **Resolution**: 
    *   If a Counter is activated, it resolves first.
    *   The original event then resolves (if not cancelled/modified by the Counter).
    *   Effects generated during resolution **do not** create additional Response Windows.
5.  **Completion**: The event is complete. The game state is updated once and for all.

**No Target Pivoting**: Once an event is declared with a specific target, that target is fixed for the duration of the pending event. If the declared target is no longer present or legal when the event resolves, the event does not select a replacement target and does not change into another form of event. For attacks, a missing or illegal declared defender causes the attack to fail; an attack against a Unit does not become a Direct Attack.

**Defense Target Removal**: If a declared Defense Mode target leaves play before the attack resolves, the attack fails. The attacker does not redirect to another Unit or to the opponent's LP.

---

## II. Category Specifications

### 1. Normal Support
*   **Timing**: Main Phase only.
*   **Zone**: No zone (Hand $\rightarrow$ Resolution $\rightarrow$ Discard).
*   **Response**: Counterable.
*   **Resolution**: Atomic. If countered, no effect occurs.

### 2. Equip Support
*   **Timing**: Main Phase only.
*   **Zone**: Attached to a Unit.
*   **Response**: Counterable. Does not attach until resolution.
*   **Dependency**: Bound to the Unit. If the Unit leaves play, the Equip is sent to the Discard Pile.
*   **Limits**: Multiple Equips permitted per Unit. No target changes after attachment.

### 3. Field Support
*   **Timing**: Main Phase only.
*   **Zone**: Support Zone.
*   **Response**: Counterable. Persistent effect begins only after resolution.
*   **Occupancy**: Multiple Fields can coexist. Playing a new Field does **not** replace existing ones.
*   **Persistence**: Applies continuously while the card remains in the Support Zone.

### 4. Counter Support
*   **Timing**: Set in Support Zone (Main Phase) $\rightarrow$ Activated during a Response Window.
*   **Zone**: Support Zone $\rightarrow$ Discard.
*   **Response**: Activation does **not** create a new response window.
*   **Eligible Events**: Only "Counterable" events (Normal/Equip/Field plays and Attacks).
*   **Limits**: Only one Counter per event. Cannot Counter own events. Cannot Counter other Counters.

---

## III. Hard-Locked Rule Resolutions

### 1. The "Attack Spent" Rule
A declared attack is considered initiated upon declaration. If the attack is Countered and cancelled, the attacking Unit **has still used its attack for the turn**.

### 2. Persistent Effect Layering
Vallen does **not** use a "last played" or "owner" priority system.
*   **Cumulative**: All active Field and Equip effects apply simultaneously.
*   **Net Results**: Conflicting stats (e.g., +100 ATK and -100 ATK) result in a net sum (0).
*   **Absolutes**: Contradictory absolute rules (e.g., "Cannot attack" vs "Can attack twice") must be resolved by specific card text. If no text exists, the restrictive rule takes precedence.

### 3. State Entry
Persistent effects (Fields/Equips) apply to objects only **after** they have successfully entered the state to which the effect applies. A Unit pending summon does not benefit from a Field effect until the summon resolves.

### 4. Identity & Removal
If an Equip or Field is removed, its effect stops immediately. Any dependent effects are re-evaluated based on the new state.
