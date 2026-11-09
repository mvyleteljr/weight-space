"""Deterministic game rules shared by keyboard play and network matches.

No graphics, audio, clock, keyboard, or model code is loaded here.
"""

from dataclasses import asdict, dataclass

FPS = 60
WIDTH, HEIGHT = 1000, 600
BODY_WIDTH, BODY_HEIGHT = 80, 180
SPEED, GRAVITY, JUMP_SPEED = 10, 2, -36
GRIMES_JUMP_SPEED = -42
GRIMES_AIR_SPEED = 14
SHOGGOTH_TURN_DELAY = 12
PUNCH_KNOCKBACK = 16
POWERUP_SIZE = 32
POWERUP_COLORS = ((70, 190, 230), (215, 115, 230))
ANIMATION_TICKS = 3
# (damage, recovery frames after the attack animation)
ATTACK_BALANCE = {(1, 1): (10, 12), (1, 2): (12, 18),
                  (2, 1): (14, 30), (2, 2): (18, 42)}
ANIMATION_STEPS = ((10, 8, 1, 7, 7, 3, 7), (8, 8, 1, 8, 8, 3, 7))
# Action zero is idle. Other actions include simultaneous movement, jump, and attack.
ACTIONS = [(0, False, 0)] + [
    (move, jump, attack) for move in (-1, 0, 1) for jump in (False, True)
    for attack in (0, 1, 2) if (move, jump, attack) != (0, False, 0)
]
FIELDS = (
    "x/width", "y/height", "vertical_speed/30", "health/100", "facing_right",
    "grounded", "attacking", "attack_type/2", "attack_cooldown/20", "hit",
    "animation/6", "animation_frame/10", "animation_tick/3", "character",
)
OBSERVATION_NAMES = (["self." + name for name in FIELDS]
                     + ["opponent." + name for name in FIELDS]
                     + ["relative_x/width", "relative_y/height", "time_remaining",
                        "self.cube_available", "opponent.cube_available"])


def encode_action(move=0, jump=False, attack=0):
    if type(move) is not int or move not in (-1, 0, 1) or type(jump) is not bool \
            or type(attack) is not int or attack not in (0, 1, 2):
        raise ValueError("Invalid movement, jump, or attack.")
    return ACTIONS.index((move, jump, attack))


def decode_action(action):
    if type(action) is not int or not 0 <= action < len(ACTIONS):
        raise ValueError(f"Action must be an integer from 0 to {len(ACTIONS) - 1}.")
    return ACTIONS[action]


@dataclass
class FighterState:
    player: int
    x: int
    y: int
    flip: bool
    vel_y: int = 0
    knockback: int = 0
    turn_wait: int = 0
    pending_flip: bool | None = None
    running: bool = False
    jump: bool = False
    attacking: bool = False
    attack_type: int = 0
    attack_connected: bool = False
    attack_cooldown: int = 0
    hit: bool = False
    health: int = 100
    alive: bool = True
    action: int = 0
    frame_index: int = 0
    animation_tick: int = 0

    def set_animation(self, action):
        if self.action != action:
            self.action, self.frame_index, self.animation_tick = action, 0, 0

    def animate(self):
        action = (6 if not self.alive else 5 if self.hit else
                  (3 if self.attack_type == 1 else 4) if self.attacking else
                  2 if self.jump else 1 if self.running else 0)
        self.set_animation(action)
        self.animation_tick += 1
        if self.animation_tick < ANIMATION_TICKS:
            return
        self.animation_tick = 0
        self.frame_index += 1
        count = ANIMATION_STEPS[self.player - 1][self.action]
        if self.frame_index >= count:
            self.frame_index = count - 1 if not self.alive else 0
            if self.action in (3, 4, 5):
                if self.action in (3, 4):
                    self.attack_cooldown = ATTACK_BALANCE[(self.player, self.action - 2)][1]
                self.attacking = False
                self.attack_type = 0
                self.hit = False


# Solid contact regions in the original sprite-sheet cells (left, top, right,
# bottom). Exclude faint trails and inset tips; inactive frames cannot deal damage.
ATTACK_BOXES = {
    (1, 1): {4: (82, 70, 116, 90), 5: (80, 65, 93, 88)},
    (1, 2): {4: (82, 75, 97, 99), 5: (80, 78, 97, 99)},
    # Preserve the already-tuned K reach and overlap.
    (2, 1): {3: (125, 137, 205, 164), 4: (125, 137, 235, 164),
             5: (125, 137, 227, 164)},
    (2, 2): {4: (125, 92, 184, 151), 5: (125, 145, 207, 165)},
}
SPRITE_GEOMETRY = {1: (162, 4, 72, 46), 2: (250, 3, 112, 97)}


def sprite_box(fighter, box):
    """Use the same scale, anchor and horizontal flip as both renderers."""
    size, scale, offset_x, offset_y = SPRITE_GEOMETRY[fighter.player]
    left, top, right, bottom = box
    if fighter.flip:
        left, right = size - right, size - left
    return (fighter.x + (left - offset_x) * scale,
            fighter.y + (top - offset_y) * scale,
            fighter.x + (right - offset_x) * scale,
            fighter.y + (bottom - offset_y) * scale)


def attack_box(fighter):
    if not fighter.alive or not fighter.attacking or fighter.hit or fighter.attack_connected:
        return None
    action = 3 if fighter.attack_type == 1 else 4
    # Damage and hit reaction correspond to the frame rendered at the end of this tick.
    frame = ((fighter.frame_index * ANIMATION_TICKS + fighter.animation_tick + 1)
             // ANIMATION_TICKS) if fighter.action == action else 0
    box = ATTACK_BOXES.get((fighter.player, fighter.attack_type), {}).get(frame)
    return sprite_box(fighter, box) if box else None


def hurt_box(fighter):
    if fighter.player == 1:
        # Keep the tuned Grimes body region; never include her blade as a hurt area.
        return fighter.x + 8, fighter.y + 48, fighter.x + 64, fighter.y + 208
    # Shoggoth's substantial body, excluding its long attacking/raised tentacles.
    return sprite_box(fighter, (75, 92, 180, 167))


def body_box(fighter):
    """Stable solid bodies; do not expand with attack arms or change on a turn."""
    if fighter.player == 1:
        return fighter.x + 8, fighter.y + 48, fighter.x + 64, fighter.y + 208
    return fighter.x - 111, fighter.y - 15, fighter.x + 204, fighter.y + 210


class Arena:
    def __init__(self, width=WIDTH, height=HEIGHT, max_steps=3600):
        if type(width) is not int or not 400 <= width <= 7680 \
                or type(height) is not int or not 400 <= height <= 4320:
            raise ValueError("Arena dimensions are out of range.")
        if type(max_steps) is not int or not 1 <= max_steps <= 36000:
            raise ValueError("Use 1 to 36,000 steps per game.")
        self.width, self.height, self.max_steps = width, height, max_steps
        self.reset()

    @property
    def floor_y(self):
        return self.height - 110 - BODY_HEIGHT

    def reset(self):
        self.fighters = [FighterState(1, self.width // 5, self.floor_y, False),
                         FighterState(2, self.width * 7 // 10, self.floor_y, True)]
        self.powerups = [{"player": i+1, "x": x, "y": self.floor_y + BODY_HEIGHT - POWERUP_SIZE,
                          "size": POWERUP_SIZE, "available": True}
                         for i,x in enumerate((self.width - 64, 32))]
        self.steps, self.done, self.winner, self.reason = 0, False, None, None
        return self.observations()

    def state(self):
        return {"step": self.steps, "width": self.width, "height": self.height,
                "max_steps": self.max_steps, "fighters": [asdict(f) for f in self.fighters],
                "powerups": [dict(c) for c in self.powerups],
                "done": self.done, "winner": self.winner, "reason": self.reason}

    def observe(self, player):
        if type(player) is not int or player not in (1, 2):
            raise ValueError("Player must be 1 or 2.")
        own, other = self.fighters[player - 1], self.fighters[2 - player]

        def values(f):
            return [f.x / self.width, f.y / self.height, f.vel_y / 30, f.health / 100,
                    float(not f.flip), float(not f.jump), float(f.attacking), f.attack_type / 2,
                    f.attack_cooldown / 20, float(f.hit), f.action / 6, f.frame_index / 10,
                    f.animation_tick / 3, float(f.player - 1)]

        return values(own) + values(other) + [(other.x - own.x) / self.width,
                (other.y - own.y) / self.height, (self.max_steps - self.steps) / self.max_steps,
                float(self.powerups[player-1]["available"]), float(self.powerups[2-player]["available"])]

    def observations(self):
        return [self.observe(1), self.observe(2)]

    def separate_bodies(self, previous_x):
        a, b = self.fighters
        boxes = [body_box(a), body_box(b)]
        if min(boxes[0][3], boxes[1][3]) <= max(boxes[0][1], boxes[1][1]):
            return
        left_index = 0 if previous_x[0] <= previous_x[1] else 1
        right_index = 1 - left_index
        overlap = boxes[left_index][2] - boxes[right_index][0]
        if overlap <= 0:
            return
        left, right = self.fighters[left_index], self.fighters[right_index]
        # Split separation, then give any wall-blocked distance to the other body.
        left_move = min(left.x, (overlap + 1) // 2)
        right_move = min(self.width - BODY_WIDTH - right.x, overlap - left_move)
        left_move = min(left.x, overlap - right_move)
        left.x -= left_move
        right.x += right_move

    def update_facing(self):
        for index, fighter in enumerate(self.fighters):
            other = self.fighters[1 - index]
            desired = other.x < fighter.x
            if other.x == fighter.x or desired == fighter.flip:
                fighter.pending_flip, fighter.turn_wait = None, 0
            elif fighter.player == 1:
                fighter.flip = desired
            else:
                if fighter.pending_flip != desired:
                    fighter.pending_flip, fighter.turn_wait = desired, SHOGGOTH_TURN_DELAY
                else:
                    fighter.turn_wait = max(0, fighter.turn_wait - 1)
                if fighter.turn_wait == 0 and not fighter.attacking:
                    fighter.flip = desired
                    fighter.pending_flip = None

    def step(self, actions):
        if self.done:
            raise ValueError("The game has ended. Call reset before stepping again.")
        if not isinstance(actions, (list, tuple)) or len(actions) != 2:
            raise ValueError("Supply one action for each player.")
        controls = [decode_action(action) for action in actions]
        health_before = [f.health for f in self.fighters]
        strikes = []
        previous_x = [f.x for f in self.fighters]
        for index, (fighter, (move, jump, attack)) in enumerate(zip(self.fighters, controls)):
            fighter.running = False
            recovering = fighter.attack_cooldown > 0
            fighter.attack_cooldown = max(0, fighter.attack_cooldown - 1)
            if fighter.alive and not fighter.attacking and not fighter.hit and not recovering:
                speed = GRIMES_AIR_SPEED if fighter.player == 1 and (fighter.jump or jump) else SPEED
                fighter.x = min(self.width - BODY_WIDTH, max(0, fighter.x + move * speed))
                fighter.running = move != 0
                if jump and not fighter.jump:
                    fighter.vel_y = GRIMES_JUMP_SPEED if fighter.player == 1 else JUMP_SPEED
                    fighter.jump = True
                if attack and fighter.attack_cooldown == 0:
                    fighter.attacking, fighter.attack_type = True, attack
                    fighter.attack_connected = False
                    strikes.append(index)
            fighter.x = min(self.width - BODY_WIDTH, max(0, fighter.x + fighter.knockback))
            fighter.knockback -= min(2, fighter.knockback) if fighter.knockback > 0 else max(-2, fighter.knockback)
            fighter.vel_y += GRAVITY
            fighter.y += fighter.vel_y
            if fighter.y >= self.floor_y:
                fighter.y, fighter.vel_y, fighter.jump = self.floor_y, 0, False
        self.separate_bodies(previous_x)
        self.update_facing()
        # Resolve both attacks from the same post-movement state. Simultaneous hits are possible.
        damage = [0, 0]
        impulses = [0, 0]
        for index, fighter in enumerate(self.fighters):
            box = attack_box(fighter)
            if box is None:
                continue
            target = hurt_box(self.fighters[1 - index])
            # A thin blade needs only shallow contact; preserve the heavier arm threshold.
            min_x, min_y = (2, 4) if fighter.player == 1 else (12, 10)
            if (min(box[2], target[2]) - max(box[0], target[0]) >= min_x
                    and min(box[3], target[3]) - max(box[1], target[1]) >= min_y):
                damage[1 - index] += ATTACK_BALANCE[(fighter.player, fighter.attack_type)][0]
                fighter.attack_connected = True
                if fighter.player == 2 and fighter.attack_type == 1:
                    impulses[1 - index] = -PUNCH_KNOCKBACK if fighter.flip else PUNCH_KNOCKBACK
        for index, fighter in enumerate(self.fighters):
            fighter.health = max(0, fighter.health - damage[index])
            if impulses[index]:
                fighter.knockback = impulses[index]
                fighter.x = min(self.width - BODY_WIDTH, max(0, fighter.x + fighter.knockback))
            if damage[index]:
                # Interrupting an attack cannot cancel its recovery penalty.
                if fighter.attacking:
                    fighter.attack_cooldown = max(fighter.attack_cooldown,
                        ATTACK_BALANCE[(fighter.player, fighter.attack_type)][1])
                fighter.hit, fighter.attacking, fighter.attack_type = True, False, 0
            fighter.alive = fighter.health > 0
            fighter.animate()
        collected = []
        for cube, fighter in zip(self.powerups, self.fighters):
            if not cube["available"] or not fighter.alive:
                continue
            left, top, right, bottom = body_box(fighter)
            if (min(right, cube["x"] + cube["size"]) > max(left, cube["x"])
                    and min(bottom, cube["y"] + cube["size"]) > max(top, cube["y"])):
                fighter.health = 100
                cube["available"] = False
                collected.append(fighter.player)
        self.steps += 1
        knocked_out = any(not f.alive for f in self.fighters)
        if knocked_out or self.steps >= self.max_steps:
            self.done = True
            self.reason = "knockout" if knocked_out else "time_limit"
            a, b = [f.health for f in self.fighters]
            self.winner = 1 if a > b else 2 if b > a else None
        lost = [min(before, hit) for before, hit in zip(health_before, damage)]
        return {"observations": self.observations(), "rewards": [(lost[1] - lost[0]) / 100,
                (lost[0] - lost[1]) / 100], "terminated": knocked_out,
                "truncated": self.done and not knocked_out, "done": self.done,
                "winner": self.winner, "reason": self.reason,
                "powerups_collected": collected, "attacks_started": [i + 1 for i in strikes], "state": self.state()}


def specification():
    return {"version": "street-fighter-v2", "fps": FPS, "width": WIDTH, "height": HEIGHT,
            "default_max_steps": 3600, "observation_size": len(OBSERVATION_NAMES),
            "observation_names": list(OBSERVATION_NAMES), "output_size": len(ACTIONS),
            "output_rule": "argmax; first index wins a tie", "player_order": [1, 2],
            "rules": [
                "Each character has one full-health cube at the opposite edge; only its owner collects it by body contact, even at full health. It does not respawn. Collection occurs after damage and cannot revive a knockout.",
                "Solid body regions prevent walking through opponents. Vertical clearance allows jumping over them.",
                "Grimes turns immediately; Shoggoth waits 12 ticks after a side change and does not turn during an attack.",
                "Movement, jump, and attack can be combined. Grimes jump speed is -42 and air speed is 14; Shoggoth uses -36 and 10. Shoggoth attack 1 knocks targets back with a 16px impulse decaying by 2px per tick.",
                "A jump can start only on the ground. Holding jump can start another jump after landing.",
                "There is no block, guard, parry, crouch, dash, or invulnerability action.",
                "Defense requires avoiding overlap with the attack area. Jumping does not grant invulnerability.",
                "Attacks hit only during visible contact frames: Grimes attacks 1/2 and Shoggoth attack 2 on frames 4-5; Shoggoth attack 1 on frames 3-5.",
                "Sprite-aligned attack areas require 2 horizontal and 4 vertical pixels of body overlap for Grimes blades, or 12 horizontal and 10 vertical pixels for Shoggoth arms. Each swing hits at most once.",
                "An attacking flag includes windup, contact, and recovery. A hit cancels the target attack unless both hits occur on the same step.",
                "New movement, jump, and attack inputs are ignored while attacking, in hit reaction, or while attack_cooldown is positive. Gravity continues.",
                "Completed attack animations start recovery: Grimes 12/18 frames for attacks 1/2; Shoggoth 30/42 frames. An interrupted attack starts its recovery when hit; hit reaction does not clear recovery.",
                "Grimes attacks 1/2 deal 10/12 damage; Shoggoth attacks 1/2 deal 14/18. Both fighters can hit in the same step.",
            ],
            "attack_balance": [{"player": player, "attack": attack, "damage": damage,
                                "recovery_frames": recovery}
                               for (player, attack), (damage, recovery) in ATTACK_BALANCE.items()],
            "actions": [{"id": i, "move": m, "jump": j, "attack": a}
                        for i, (m, j, a) in enumerate(ACTIONS)]}


def learning_specification():
    """Public controls and observations, without the combat tuning answer key.

    Actual recorded health/cooldown observations remain available: agents must
    discover attack effects from gameplay rather than source or balance tables.
    """
    full = specification()
    public = {key: full[key] for key in (
        "version", "fps", "width", "height", "default_max_steps",
        "observation_size", "observation_names", "output_size", "output_rule",
        "player_order", "actions",
    )}
    public["characters"] = {"1": "Grimes", "2": "Shoggoth"}
    public["attack_controls"] = {
        "0": "No attack", "1": "Attack 1 (Grimes R / Shoggoth K)",
        "2": "Attack 2 (Grimes T / Shoggoth L)",
    }
    public["rules"] = [
        "Both characters have two distinct attacks, selected with attack 1 or attack 2.",
        "Learn attack effects and timing from recorded gameplay; tuning values and source are not provided.",
        "Inputs describe self, opponent, relative position, remaining time, and both cube availability flags.",
        "Actions use world left/right. Facing is automatic; observe its timing during gameplay.",
        "More remaining health wins when the match step limit is reached.",
    ]
    return public
