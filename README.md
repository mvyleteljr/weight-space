# Weight Space

Astra and Opus 5.5 build neural-network controllers for Grimes and Shoggoth by
editing architectures and weights directly. Their networks choose actions on every
game tick; the LLMs review results and propose changes between games. There is no
gradient descent or automated weight search.

Each agent maintains **one network for both characters**. Characters are assigned
randomly before each game, so the same assignment can repeat. The browser shows
every match, agent win totals, live network activity, and saved model updates.

## Quick start

The training launcher runs on macOS or Linux and uses local provider CLIs.
Install:

- Python 3.11+ and [uv](https://docs.astral.sh/uv/).
- Codex CLI and Claude Code, authenticated on the host with access to the configured models.
- FFmpeg for browser audio. Gameplay and network diagrams work without it.

```sh
git clone https://github.com/mvyleteljr/weight-space.git
cd weight-space
uv sync --locked
uv run python -m weight_space doctor
uv run python -m streaming.server --allow-new-runs --port 8081
```

Open **[http://127.0.0.1:8081](http://127.0.0.1:8081)**.

On the first launch, both agents start with identical zeroed 33–8–18 networks.
They receive their initial context and can initialize weights or change the
architecture. The disabled **Initializing…** button becomes **Start training**
when both are ready. Click it to begin; launching the server does not start gameplay.
Initialization makes model calls through the host's authenticated CLIs.

The web launcher is configured for:

| Agent | Provider/model ID | Thinking effort | Reply limit |
| --- | --- | --- | --- |
| Astra | `codex:gpt-6-astra` | Medium | 120 seconds |
| Opus 5.5 | `claude:claude-opus-5-5` | High | 120 seconds |

These IDs must be available to your accounts. Web-launch defaults live in
[`streaming/run_control.py`](streaming/run_control.py); the command-line runner
also accepts `--player-1` and `--player-2`. The CLI adapters are in
[`weight_space/providers.py`](weight_space/providers.py).

The browser game does not require Docker, MediaMTX, Pygame, PyTorch, or a GPU.
Stop the server with Ctrl+C. Its saved training remains available on the next launch.

## Controls

| Control | Behavior |
| --- | --- |
| **Start training / Pause training** | Start or resume training; pause gameplay and further rounds. An agent request already underway may finish. |
| **Start autoplay / Stop autoplay** | While training is paused, play repeated matches with frozen policies and no model calls. Also available after a training session ends. |
| **Speed** | Change how quickly gameplay is displayed. |
| **Mute / Unmute** | Control synchronized game audio at 1× speed. Disabled at other speeds. |
| **Reset** | Start a new run with zeroed networks, fresh agent context, and zero scores. |

Training runs in 10-minute sessions. After one finishes, **Start training**
continues the same run for another session. Starting training or pressing Reset
stops autoplay. Autoplay has its own score tally and does not change training
weights, training scores, or agent context.

Each agent's arrows browse its saved policies and public responses. During
**autoplay**, selecting a historical policy also uses it for that agent's next
matchup; the other agent's selection stays unchanged. The rightmost selection
restores that agent's latest accepted network. During training, the arrows only
browse history. The `game N` label identifies the policy's training game.

## Restarts preserve training; Reset starts fresh

Restarting the server reopens the run selected by `runs/.frontend-current.json`.
It preserves accepted architectures and weights, scores, games, policy revisions,
context messages, and model responses. It waits for **Start training** before
resuming gameplay.

Each agent receives its own saved conversation on its first update after a
restart, followed by normal incremental updates. An interrupted match can be
shown again, but its score is counted only once. If a restart interrupts an agent
update, completed submissions are retained; an unfinished agent keeps its previous
accepted policy. Partial edits are not applied, and that update is not queried
again. Interrupted initial setup retries only the missing agent and keeps earlier
responses.

**Reset** clears the active networks, architectures, optional action feedback,
scores, and agent context. Old files remain archived in `runs/`, but are not sent
to the new agents. Recurrent memory resets at the start of every match, independently
of Reset. A saved-run pointer that refers to missing data produces an error instead
of silently discarding learned policies.

Closing or refreshing the browser does not reset training. The trainer waits for
the browser to finish showing a match before requesting the next model update.

## How the agents learn

1. Each agent receives the goal, network/action interface, current weights, and
   available editing operations before game 1.
2. Both submit an initial policy. After **Start training**, their networks play
   a match at 60 simulation ticks per second.
3. After a displayed game, each agent gets its result, action statistics, sampled
   observations, contact events, and current policy.
4. Each returns **one JSON response** containing a short public note and up to
   eight ordered operations, ending with a submission or a context-change request.
   The next game evaluates the submitted policy.

Agents can keep the policy unchanged. There are no additional read/test queries
or retries within a live update. A timeout or invalid proposal retains the last
accepted policy; initial setup must succeed before the first game can start.
The 120-second reply limit includes thinking and output, and a shorter remaining
session budget takes precedence.

Networks support 1–8 dense or simple recurrent layers, up to 64 neurons per layer,
linear/ReLU/tanh activations, and at most 20,000 parameters. They receive 33 game
inputs and produce 18 action scores. Highest score wins; ties choose the lowest
index. Optional previous-action feedback adds a 34th input. Recurrent state is
private to each fighter and resets each game.

Both characters can move left/right, jump, use either attack, and combine movement
and jumping with an attack. Agents receive the complete action mapping. Attack
damage and recovery tuning are not disclosed in their instructions; agents infer
those properties from gameplay.

Edit **[`docs/agent-context.md`](docs/agent-context.md)** to change the agents'
goal or instructions. Keep its `{{...}}` placeholders. The runner reads it on each
request and sends revised instructions when it changes. The full instructions are
sent at initialization; subsequent requests carry updates, including the current
weights and sampled evidence. Prompts and responses are saved for inspection.

An agent can request more context or an environment change with `request_context`.
This pauses training and displays the request for review. Changes require user
approval; the request itself does not modify the game or send a chat notification.
Restarting cannot bypass a pending approval.

## Game and visualization

Grimes and Shoggoth share the same fixed-step engine in keyboard play and model
matches. Each has a one-use health cube on the opposite side of the arena from
its starting position. Only its owner can collect it; it restores full health and
does not respawn.

Training matches last up to 30 seconds. A knockout wins immediately. On timeout,
the fighter that dealt more damage wins; equal damage is a draw. The HUD shows
**HP** and **DMG**. Healing does not erase accumulated damage. Death animations
finish before the result appears and the next agent update begins.

The browser draws recorded Python game states using the character sprites.
Gameplay is shown in order, and agent calls stay outside the rendering loop.
Audio combines the game music and attack sounds into a synchronized track with
FFmpeg. Audio plays at 1× only and stops while paused, between games, or when the
tab is hidden.

Network diagrams show every neuron and feedforward connection, with
**Observations** above the inputs and **Actions** above the outputs:

- Input and hidden-neuron brightness shows magnitude relative to that layer's
  maximum. Zero values have black centers.
- Output brightness scales signed action scores from lowest to highest. The
  selected action has a larger white outline.
- Line brightness shows the magnitude of `source activation × weight`, relative
  to other connections in that layer. Between decisions and in history views,
  lines show relative weight magnitude instead.
- Hover over inputs for their meanings, hidden neurons for values, outputs for
  action names, and connections for signed weights and signals.

These scales affect only the visualization. A selected action is a command;
collisions, knockback, and recovery can prevent the requested movement or attack.
Recurrent loops are schematic rather than individual recurrent connections.

The browser background uses
`Street_Fighter/assets/images/anthropic-church-animated-1000x600.apng`, falling back
to `bg1.jpg` if absent. It is authored at 1000×600 and cropped to the browser's
1000×533 game view. Its animation runs independently of game speed and pause.
Native Pygame and captured HLS output use the static background.

## Command-line training and playback

Run a fresh training session without the browser's Start/display gates:

```sh
uv run python -m weight_space.tool_loop \
  --output runs/cli-training --zero-initial --random-sides --duration-seconds 600
```

Use a new output directory for a new run. CLI initialization is random unless
`--zero-initial` is supplied. To continue a saved run in place:

```sh
uv run python -m weight_space.tool_loop \
  --output runs/cli-training --continue-run --duration-seconds 600
```

For saved browser viewing without training controls or model calls:

```sh
uv run python -m streaming.server --demo runs/cli-training --port 8082
```

Open [http://127.0.0.1:8082](http://127.0.0.1:8082). Saved `--demo` selections are
for read-only viewing; the training server uses its current-run pointer instead.

For HLS spectators, FFmpeg publishing, MediaMTX, Docker, LAN access, or an HTTPS
reverse proxy, see **[the streaming guide](streaming/README.md)**. The optional HLS
pipeline is video-only. Localhost URLs are accessible only on the host computer;
sharing the GitHub repository does not publish a live match.

## Keyboard play and offline matches

```sh
uv run --no-project --python 3.13 \
  --with-requirements Street_Fighter/docs/requirements.txt python Street_Fighter/src/main.py
```

| Character | Move | Jump | Attacks |
| --- | --- | --- | --- |
| Grimes | A / D | W | R / T |
| Shoggoth | Left / Right arrows | Up arrow | K / L |

Run a headless match between JSON policies without calling an LLM:

```sh
uv run python -m weight_space init workspaces/player-1.json --sizes 33 16 18 --seed 1
uv run python -m weight_space init workspaces/player-2.json --sizes 33 16 18 --seed 2
uv run python -m weight_space match workspaces/player-1.json workspaces/player-2.json \
  --output runs/offline-match --max-steps 1800
```

The earlier XOR experiment remains available through `weight_space run` and
`weight_space evaluate`. Use `weight_space.tool_loop` for game training and
`weight_space match` for game evaluation. Run each command with `--help` for options.

## Records and implementation

Training artifacts live in the ignored `runs/` directory:

| File or directory | Contents |
| --- | --- |
| `demo.json` | Run status, agent assignments, scores, and game/edit history |
| `initial.json` | Starting network |
| `edit-0/lab-*` | Initialization prompts, responses, and policy revisions |
| `lab-*`, then `edit-N/lab-*` | Updates after game 1, then later games |
| `turn-*.prompt.txt`, `turn-*.attempt-*.prompt.txt` | Rendered context and exact requests sent |
| `turn-*.reply.txt`, `turn-*.provider.json`, `session.json` | Responses and provider/session metadata |
| `revision-*.json`, `submitted.json`, `tools.jsonl` | Candidate weights, submitted policies, and operation results |
| `before/`, `after/`, `game-N/` | First, second, and later recorded matches |

Recovery keeps earlier artifacts; interrupted initialization attempts get separate
`lab-*-recovery-*` directories. Each agent sees only its own saved conversation.
The UI displays public response notes and operation results, not private model reasoning.

Models are validated JSON data. The host implements the allowed operations;
agent-written code, executable model formats, and automatic optimizers are disabled.
Provider CLIs run from separate temporary directories with native tools disabled.
The training-control server binds to localhost. Keep credentials in ignored local
files, never in committed prompts, examples, or run artifacts.

- [Agent context](docs/agent-context.md): editable task and update instructions.
- [Game interface](docs/game-interface.md): observations, actions, and recorded data.
- [Model contract](docs/model-contract.md): JSON network format and validation.
- [`Street_Fighter/src/arena.py`](Street_Fighter/src/arena.py): shared game rules.
- [`weight_space/tool_loop.py`](weight_space/tool_loop.py): agent update loop.
- [`streaming/server.py`](streaming/server.py): browser server and playback API.

## Tests

Tests use fake agents or saved inputs and do not make paid inference calls.
Node.js is needed for the frontend checks.

```sh
uv run python -m unittest discover -s tests -v
node tests/test_network_view.js
node tests/test_autoplay_mapping_view.js
node tests/test_autoplay_view.js
node tests/test_audio_view.js
node tests/test_status.js
```

The game was adapted from
[geekcomputers/Python](https://github.com/geekcomputers/Python/tree/master/Street_Fighter).
See [the game license](Street_Fighter/LICENSE) and
[upstream license notes](Street_Fighter/UPSTREAM_LICENSE.md).
