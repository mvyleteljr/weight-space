"""Deterministic game rules shared by keyboard play and network matches.

No graphics, audio, clock, keyboard, or model code is loaded here.
"""

from dataclasses import asdict, dataclass

FPS = 60
WIDTH, HEIGHT = 1000, 600
BODY_WIDTH, BODY_HEIGHT = 80, 180
SPEED, GRAVITY, JUMP_SPEED = 10, 2, -30
DAMAGE, COOLDOWN, ANIMATION_TICKS = 10, 20, 3
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
                     + ["relative_x/width", "relative_y/height", "time_remaining"])


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
    running: bool = False
    jump: bool = False
    attacking: bool = False
    attack_type: int = 0
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
                self.attacking = False
                self.attack_type = 0
                self.attack_cooldown = COOLDOWN
                self.hit = False


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
        self.steps, self.done, self.winner, self.reason = 0, False, None, None
        return self.observations()

    def state(self):
        return {"step": self.steps, "width": self.width, "height": self.height,
                "max_steps": self.max_steps, "fighters": [asdict(f) for f in self.fighters],
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
                (other.y - own.y) / self.height, (self.max_steps - self.steps) / self.max_steps]

    def observations(self):
        return [self.observe(1), self.observe(2)]

    def step(self, actions):
        if self.done:
            raise ValueError("The game has ended. Call reset before stepping again.")
        if not isinstance(actions, (list, tuple)) or len(actions) != 2:
            raise ValueError("Supply one action for each player.")
        controls = [decode_action(action) for action in actions]  # Validate both before mutation.
        health_before = [f.health for f in self.fighters]
        strikes = []
        for index, (fighter, (move, jump, attack)) in enumerate(zip(self.fighters, controls)):
            fighter.running = False
            fighter.attack_cooldown = max(0, fighter.attack_cooldown - 1)
            if fighter.alive and not fighter.attacking and not fighter.hit:
                fighter.x = min(self.width - BODY_WIDTH, max(0, fighter.x + move * SPEED))
                fighter.running = move != 0
                if jump and not fighter.jump:
                    fighter.vel_y, fighter.jump = JUMP_SPEED, True
                if attack and fighter.attack_cooldown == 0:
                    fighter.attacking, fighter.attack_type = True, attack
                    strikes.append(index)
            fighter.vel_y += GRAVITY
            fighter.y += fighter.vel_y
            if fighter.y >= self.floor_y:
                fighter.y, fighter.vel_y, fighter.jump = self.floor_y, 0, False
        for index, fighter in enumerate(self.fighters):
            other = self.fighters[1 - index]
            if other.x != fighter.x:
                fighter.flip = other.x < fighter.x
        # Resolve both attacks from the same post-movement state. Simultaneous hits are possible.
        damage = [0, 0]
        for index in strikes:
            fighter, target = self.fighters[index], self.fighters[1 - index]
            left = fighter.x + BODY_WIDTH // 2 - (2 * BODY_WIDTH if fighter.flip else 0)
            if (left < target.x + BODY_WIDTH and left + 2 * BODY_WIDTH > target.x
                    and fighter.y < target.y + BODY_HEIGHT and fighter.y + BODY_HEIGHT > target.y):
                damage[1 - index] += DAMAGE
        for index, fighter in enumerate(self.fighters):
            fighter.health = max(0, fighter.health - damage[index])
            if damage[index]:
                fighter.hit, fighter.attacking, fighter.attack_type = True, False, 0
            fighter.alive = fighter.health > 0
            fighter.animate()
        self.steps += 1
        knocked_out = any(not f.alive for f in self.fighters)
        if knocked_out or self.steps >= self.max_steps:
            self.done = True
            self.reason = "knockout" if knocked_out else "time_limit"
            a, b = [f.health for f in self.fighters]
            self.winner = 1 if a > b else 2 if b > a else None
        lost = [before - f.health for before, f in zip(health_before, self.fighters)]
        return {"observations": self.observations(), "rewards": [(lost[1] - lost[0]) / 100,
                (lost[0] - lost[1]) / 100], "terminated": knocked_out,
                "truncated": self.done and not knocked_out, "done": self.done,
                "winner": self.winner, "reason": self.reason,
                "attacks_started": [i + 1 for i in strikes], "state": self.state()}


def specification():
    return {"version": "street-fighter-v1", "fps": FPS, "width": WIDTH, "height": HEIGHT,
            "default_max_steps": 3600, "observation_size": len(OBSERVATION_NAMES),
            "observation_names": list(OBSERVATION_NAMES), "output_size": len(ACTIONS),
            "output_rule": "argmax; first index wins a tie", "player_order": [1, 2],
            "actions": [{"id": i, "move": m, "jump": j, "attack": a}
                        for i, (m, j, a) in enumerate(ACTIONS)]}
