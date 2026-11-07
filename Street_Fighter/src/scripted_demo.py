"""Deterministic spectator demo; actions use the shared Arena rules, without AI."""
if __package__:
    from .arena import encode_action
else:
    from arena import encode_action


def scripted_actions(arena):
    actions = []
    for fighter, opponent in (arena.fighters, arena.fighters[::-1]):
        distance = opponent.x - fighter.x
        move = (1 if distance > 0 else -1) if abs(distance) > 90 else 0
        # Use simulation time so the routine is repeatable at any render rate.
        tick = arena.steps * 1000 // 60 + fighter.player * 370
        jump = tick % 2300 < 100
        attack = (1 if fighter.player == 1 else 2) if abs(distance) < 160 and tick % 1100 < 600 else 0
        actions.append(encode_action(move, jump, attack))
    return actions
