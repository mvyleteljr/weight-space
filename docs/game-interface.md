# Street Fighter model interface

The trusted game engine is `Street_Fighter/src/arena.py`. It has no graphics,
audio, keyboard, wall-clock, or network dependency. The keyboard game and model
matches use the same engine. Agent-written Python remains disabled.

## Commands

```sh
uv run python -m weight_space game-spec
uv run python -m weight_space init workspaces/player-1.json --sizes 31 16 18 --seed 1
uv run python -m weight_space init workspaces/player-2.json --sizes 31 16 18 --seed 2
uv run python -m weight_space match workspaces/player-1.json workspaces/player-2.json --output runs/match-01
```

`init` creates fresh weights. Edit the JSON to program a policy. The model must
have 31 inputs and 18 outputs. The highest output selects the action. The first
index wins a tie. Action ID zero selects idle. All other architecture rules remain
in the [model contract](model-contract.md).

`match` saves both model files before the first step and keeps private copies
for inference. Edits to the working files cannot change an active match. The
output directory must be new. Use `--max-steps` to change the default 3,600 steps.

## Trusted engine API

```python
from Street_Fighter.src.arena import Arena, encode_action

game = Arena()
observations = game.reset()
result = game.step([encode_action(move=1), encode_action(move=-1, attack=1)])
player_one_observation = game.observe(1)
state = game.state()
```

`reset()` starts a new game and returns both observations in player order.
`observe(1)` and `observe(2)` return new lists. `state()` returns a copy of the
complete state. `step([action_1, action_2])` advances one simulation frame.
Both actions must be valid before the state can change. Do not step after the
game ends; call reset first.

The step result contains:

- `observations`: both observations after the step.
- `rewards`: damage dealt minus damage received, divided by 100, for each player.
- `terminated`: a knockout occurred.
- `truncated`: the time limit ended the game without a knockout.
- `done`: either end condition occurred.
- `winner`: 1, 2, or null for a draw.
- `reason`: `knockout`, `time_limit`, or null while play continues.
- `state`: the complete state after the step.
- `attacks_started`: player IDs used by the display to play sounds.

## Observations and actions

Use `game-spec` or [game-spec.json](game-spec.json) for the exact ordered fields
and action IDs. The first 14 inputs describe the player. The next 14 describe the
opponent. The final three give relative x, relative y, and remaining time.

Each fighter has position, vertical speed, health, facing direction, ground
contact, attack state, attack type, cooldown, hit state, animation state, animation
frame, animation tick, and character ID. Character 0 is the warrior; character 1
is the wizard. Facing right is 1 and facing left is 0. Values are scaled as shown
in the field names. They are not all restricted to the range 0 to 1.

There are 18 combinations of movement (-1 left, 0 stay, 1 right), jump (off/on),
and attack (0 none, 1 first attack, 2 second attack). These controls can occur in
the same frame. Jump requests are ignored in the air. Movement, jump, and attack
requests are ignored while hit or attacking. Gravity and animation still advance.

Both policies receive the same pre-step state from their own perspective. The
engine applies movement, updates facing, then resolves both attacks together.
Two fighters can hit or knock out each other in the same step.

Fighters have no body collision. They can overlap and pass through each other.
They turn toward each other after movement. Horizontal movement also works in
the air. There is no block, guard, crouch, parry, dash, or invulnerability action.
Defense requires avoiding the attack area through position and timing.

Both attacks use the same area, which is 160 pixels wide and 180 pixels tall.
The area starts at the fighter center and extends forward. Its top is at the
fighter's body top. There is no separate low strike. A jump avoids a grounded
attack only when the bodies no longer overlap vertically at the hit check.
Starting a jump on the same step as a nearby attack does not provide immunity.

An attack checks for damage only on the step when it starts. The later attack
animation does not repeat that check. Thus, an observed `attacking` flag describes
an attack whose hit check has already occurred. The interface includes these
rules so the editing agents do not have to infer them from action names.

## Timing and game rules

The default arena is 1,000 by 600 pixels. One step is 1/60 of a simulated second.
Matches run as fast as the CPU permits; they do not wait for a wall clock. The
default limit is 60 simulated seconds. There is no random state in this version.
Identical actions and settings produce identical states.

The engine keeps the original movement speed, gravity, jump speed, hit boxes,
damage, and character animation lengths. Animation advances every three steps.
The original keyboard loop used wall-clock animation and updated players in order.
The shared engine uses fixed timing and simultaneous hit resolution instead.
Hit recovery blocks new inputs. Attack type remains set until recovery ends.

A knockout ends the game immediately. At the time limit, the fighter with more
health wins. Equal health is a draw. Player 1 is always the warrior and player 2
is the wizard. Swap model sides in a match series to account for character and
starting-position differences.

## Saved feedback

Each match writes:

- `player-1.json` and `player-2.json`: the tested models.
- `manifest.json`: interface specification, model hashes, initial state, and status.
- `steps.jsonl`: pre-step observations, chosen actions, next observations, rewards,
  and complete post-step states.
- `result.json`: the winner, end reason, final health, and number of steps.

Action traces can be replayed through `Arena.step`. These records supply feedback
for the next weight-edit round. The `run` command still drives the XOR proxy;
automatic agent revisions and scheduling between fighting matches are separate
from this interface.

## Display and SDL

SDL handles window, input, and audio operations for Pygame. The old dependencies
loaded an SDL copy through both Pygame and OpenCV. The game now loads and scales
backgrounds with Pygame alone. OpenCV and NumPy are no longer game dependencies.
The menu uses a cached downsampled background in place of the Gaussian blur.

Run the keyboard game from any directory:

```sh
uv run --no-project --python 3.13 --with-requirements Street_Fighter/docs/requirements.txt python Street_Fighter/src/main.py
```

A display smoke test can run without opening a window:

```sh
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run --no-project --python 3.13 --with-requirements Street_Fighter/docs/requirements.txt python Street_Fighter/src/main.py --smoke-test
```
