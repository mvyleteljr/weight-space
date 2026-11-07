# Weight Space

Agents create neural networks and set their weights directly. Training is not
permitted. Agents can inspect results and submit new weights between rounds.

## Submission safety

The runner accepts **dense JSON models only**. Agent-written Python is disabled.
There is no flag to enable it. The old worker and code-bundle evaluation methods
reject submissions without importing their source. Historical code bundles can
still be inspected as data. Their earlier test results do not establish safety.

Agents can choose dense layer sizes, weights, biases, and `linear`, `relu`, or
`tanh` activations. The trusted evaluator implements those operations. It checks
shapes, finite numbers, and parameter limits. It does not evaluate source strings,
import submitted modules, or load executable model formats such as pickle.

Read the [model contract](docs/model-contract.md). A more flexible network graph
format is a future step. New operations must be implemented in trusted code.

## Model setup and tests

Use uv for setup, commands, dependencies, and tests:

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run python -m weight_space doctor
uv run python -m weight_space init workspaces/astra/model.json --sizes 2 4 1 --seed 0
uv run python -m weight_space inspect workspaces/astra/model.json
uv run python -m weight_space evaluate workspaces/astra/model.json --records runs/manual/astra
```

Edit the JSON weights and biases directly. Initialization will not replace an
existing file. Use separate working files for each agent. Do not run scripts
written by agents on the host to create or edit weights.

The current proxy task is XOR. The network takes two binary inputs and produces
one number. The fixed output threshold is 0.5. All four test cases are public.
This tests submission and feedback. It does not measure game skill.

The format stores `weights[output_neuron][input_neuron]`. Each layer computes
`activation(weights @ inputs + bias)`. It permits up to 32 layers and 100,000
parameters. The CPU runtime uses Python and does not need PyTorch or a GPU.

## Live model calls

```sh
uv run python -m weight_space run --provider codex --model gpt-6-astra --output runs/astra-01
uv run python -m weight_space run --provider claude --model fable --output runs/fable-01
uv run --env-file .env python -m weight_space run --provider tinfoil --model glm-5-3 --output runs/glm-01 --timeout 240
uv run --env-file .env python -m weight_space run --provider tinfoil --model kimi-k3 --output runs/kimi-01 --timeout 240
```

Codex and Claude Code use their local subscription login. Both receive the task,
model, and feedback as text. Claude tools are disabled. Codex shell tools are
disabled and its sandbox is read-only. These CLIs are trusted local applications;
this configuration is not a general host isolation boundary.

Set `TINFOIL_API_KEY` in the ignored local `.env` file. The runner uses the official
Tinfoil SDK. Check available model IDs with:

```sh
uv run python -m weight_space models --filter kimi
```

On November 7, 2026, Tinfoil listed `glm-5-3` and `kimi-k3`. K3 was marked for
removal on November 12, 2026. The runner does not choose a replacement model.

Each live run starts with the same seed by default. It saves the initial model,
sends feedback, receives a new JSON model, and evaluates it. Both rounds run even
if the first passes. Set `--rounds` to change the count. Tinfoil permits up to
20,000 output tokens per call by default, including reasoning; set `--max-tokens`
to change this limit. CLI token limits remain under their own controls.

Records contain prompts, replies, provider metadata, weight files, and scores.
Each tested model has a SHA-256 identifier. The evaluator does not change its
weights. The driver does not overwrite old records. Use a new output directory
for each run. Local records are not a tamper-proof audit log.

`docs/smoke-results.json` contains the earlier dense-model results. The
`docs/custom-smoke-results.json` report is historical: its code-execution path
has been disabled. No paid inference calls are made by the local tests.

## Street Fighter

Local two-player fighting game, adapted from
[geekcomputers/Python](https://github.com/geekcomputers/Python/tree/master/Street_Fighter).
The collaborator's game code is in `Street_Fighter/`.

Run the keyboard game with uv:

```sh
uv run --no-project --python 3.13 --with-requirements Street_Fighter/docs/requirements.txt python Street_Fighter/src/main.py
```

Player 1: A/D to move, W to jump, R/T to attack.
Player 2: left/right arrows to move, up arrow to jump, K/L to attack.

Pygame now handles the background as well as the window. OpenCV and NumPy were
removed from the game dependencies. The display smoke test passes without the
duplicate SDL warning.

Human controls and model matches share a fixed-step engine. Models receive 31
state values and return 18 action scores. Run a headless match with:

```sh
uv run python -m weight_space game-spec
uv run python -m weight_space init workspaces/player-1.json --sizes 31 16 18 --seed 1
uv run python -m weight_space init workspaces/player-2.json --sizes 31 16 18 --seed 2
uv run python -m weight_space match workspaces/player-1.json workspaces/player-2.json --output runs/match-01
```

Each match saves both models, states, observations, actions, rewards, and the
outcome. Read the [game interface](docs/game-interface.md) for the full contract
and the rule changes needed for fixed timing and simultaneous actions. The `run`
command still uses XOR; the `match` command runs Street Fighter.

## Watch agents play

The frontend now includes browser playback controls and agent reply cards. Select
a run with `uv run python streaming/server.py --demo runs/YOUR_RUN --port 8081`,
then open http://127.0.0.1:8081. No desktop viewer is required. See
[browser playback](streaming/README.md) for Docker setup and the optional HLS mode.
Add `--allow-new-runs` to enable the **New run** button on the local host.
Choose 2 to 9 games. Each run starts Astra and Fable from identical fresh random
weights, switches characters each game, and lets both agents edit after each game
except the final game. The tally counts agent wins and shows draws separately.
**Restart** only restarts playback of the selected game.

The input-test loop lets Astra and Fable inspect recorded actions, read layer
activations, edit explicit weight values, and test chosen inputs before submission.
Both start with the same random 31–8–18 network. Each agent has its own candidate.
Tests run a network forward pass. They do not use an opponent or advance the game.

```sh
uv run python -m weight_space.tool_loop --output runs/astra-fable-tools-02 --seed 42
uv run --no-project --python 3.13 --with pygame==2.6.1 python -m weight_space.viewer --demo runs/astra-fable-tools-02 --paused
```

Run the viewer command in another terminal. Press E for tool counts, test counts,
revision numbers, and response wait time. Press 1 or 2 to watch either game.
The edit view also shows each reply note, requested tool, and test result as it
arrives. Use the mouse wheel over either card, or Page Up/Page Down, to scroll.
Press End to follow new replies. Use [ and ] to select an edit round. Start the
viewer with `--edits` to open this view directly. Earlier saved runs also work.
Replies appear after each CLI response completes; individual tokens do not stream.
Use `--games 3` on the tool-loop command for three games. The range is 2 to 9.
Each extra game follows another edit round. Agents receive the last game result
and keep their own last weights. Press a number key to select a completed game.
Add `--swap-sides` to switch warrior and wizard each game. Agents edit after each
game and receive their own actions, activations, and result from that game.
The viewer labels agents by the assignment in each saved game.

```sh
uv run python -m weight_space.tool_loop --output runs/astra-fable-swapped-02 --games 6 --swap-sides
```

Six games means one random baseline and five edit rounds. To hold weights fixed
for both character assignments before editing, also add `--paired-games` and use
4, 6, or 8 games. `info.recordings` gives each game's player slot and start index
for `read_steps` and `inspect_step`. Inputs always describe the agent's own fighter
first, including when it controls player 2.
Each edit round has its own time and tool limits. Records for later edit rounds
are in `edit-2`, `edit-3`, and so on. Later games are in `game-3`, `game-4`, and so on.
If a CLI reply times out, the agent gets one retry per edit round within the same
time budget. If it times out again, or the edit time expires, the next game uses
that agent's weights from the last game. Unsubmitted edits are discarded. The
reply card marks the skipped edit as `kept_previous`. Other errors still stop the
run. A timeout message shows the time limit, without the full CLI command.

Choose each provider and model with `--player-1 provider:model` and
`--player-2 provider:model`. Providers are `codex`, `claude`, and `tinfoil`.
Use `--reply-timeout 25 --edit-seconds 60` to set time limits in seconds.
Load `.env` when using Tinfoil. A timeout stops the run; it does not silently
replace an agent or reuse an untested revision.

Compare complete edit loops before choosing models:

```sh
uv run --env-file .env python -m weight_space.benchmark --output runs/speed-test-03 --models codex:gpt-6-luna tinfoil:deepseek-v4-1-flash tinfoil:gemma4-31b
```

Each candidate gets the same initial model, player side, and game feedback.
The report measures time to a tested submission. It does not measure game skill.
For quick Tinfoil calls, DeepSeek Flash and Gemma use reasoning effort `none`;
GLM, Kimi K3.1 Pro, and GPT-OSS 120B use `low`. Other models keep their defaults.
These settings follow the [Tinfoil reasoning guide](https://docs.tinfoil.sh/guides/reasoning).

The host sends a compact JSON tool list through each subscription CLI. It accepts
only the listed data operations. Native shell and code tools remain disabled.
Codex receives `--output-schema`; Claude receives `--json-schema`. The schema
allows only the seven data tools and their argument fields. Claude replies are
read from `structured_output`. Host validation still checks types, bounds, and
state before applying edits. A valid JSON shape does not prove a good strategy.
The agents can read a sequence of saved steps, inspect a step's input, activations,
scores and action, read a neuron, set numeric weights, test up to eight inputs per
call, and submit. Tests can include an expected action. A mismatch is feedback;
it does not prevent submission. Each final revision must have an input test.

The prompt asks for short replies and three to five exchanges. Both CLIs use low
reasoning effort for this loop. Each reply has a 60-second limit. Each agent has
a four-minute limit, ten replies, 40 tool calls, 12 edits, and 64 input test cases.
These limits bound the loop; they do not guarantee fast service responses.
Invalid tool calls return errors without applying partial weight edits.

Each `lab-1` or `lab-2` directory contains prompts, replies, provider metadata,
weight revisions, and `tools.jsonl`. The tool log contains arguments and results,
including full layer activations for each input test. A final match starts only
after both agents submit. No agent code runs, and no training or automatic weight
search occurs. Input tests check action selection; the final match checks play.

### Web viewing for spectators

The weight-editing workflow above is the main project. There is **one shared
Street Fighter engine**, used by keyboard play, network policies and the optional
scripted test. The broadcaster captures the weight-editing viewer, including game 1,
agent-edit progress and game 2. It never invokes models or changes weights.

Install FFmpeg with the `libx264` encoder and start Docker, then run from the repo root:

```sh
docker compose -f streaming/compose.yml up -d
uv run --no-project --python 3.13 --with pygame==2.6.1 python -m weight_space.viewer \
  --demo runs/astra-fable-tools-02 --stream rtsp://127.0.0.1:8554/match-1
```

Replace `runs/astra-fable-tools-02` with the output directory of your weight-editing
run. Start the agent tool loop in a separate terminal as shown above, or use a
completed run. The viewer polls the output and replays completed games at game
speed; it is **not a live feed of unrecorded simulation steps**. Agent calls stay
outside the render loop. Omit `--paused` for automatic playback through the edit
summary and rematch; add `--headless` for a server without a desktop.

Spectators open **http://127.0.0.1:8080** on the host. Video is silent H.264 at
30 FPS, fitted inside 1280×720 with its aspect ratio preserved. The full
1000×780 weight-editing viewer becomes 922×720 so its status panels remain visible.
HLS playback runs several seconds behind the viewer.

For other computers on a trusted LAN, change only the spectator port mapping in
`streaming/compose.yml` to `0.0.0.0:8080:8080`, recreate the services, and visit
`http://HOST_LAN_IP:8080`. Keep the RTSP publishing port private. For Internet
spectators, put an HTTPS reverse proxy in front of port 8080 and proxy both `/`
and `/live/`; configure access to suit your event. No public deployment is included.

Stop the viewer with Ctrl+C; stop services with
`docker compose -f streaming/compose.yml down`.
See [full streaming setup](streaming/README.md) for setup without Docker,
multiple matches, reconnect behavior, tests and external-network checks.

### Optional scripted streaming demo (no model calls)

Use this only to check video delivery without running weight-editing agents:

```sh
uv run --no-project --python 3.13 --with pygame==2.6.1 python Street_Fighter/src/main.py \
  --demo --headless --mute --stream rtsp://127.0.0.1:8554/match-1
```

The `--demo` switch runs repeating scripted matches through the same `Arena`:
approach the opponent, attack on a timer, and periodically jump. Normal keyboard
play remains the default when `--demo` is absent. Stop the weight-editing viewer
before publishing this demo to the same match path (or choose `match-2`).
The viewer's existing `--demo RUN_DIRECTORY` selects a saved weight-editing run;
the game command's boolean `--demo` selects the scripted test routine.

### Earlier one-reply demo

Start a two-game demo. This makes one model call to each agent. Both start with
the same random 31–8–18 network. They receive the same game 1 feedback and edit
their weights independently. The architecture stays fixed for this demo.

```sh
uv run python -m weight_space.demo --output runs/astra-fable-demo-02 --pairing astra-fable --seed 42
```

Open the viewer in another terminal while the demo runs, or after it finishes:

```sh
uv run --no-project --python 3.13 --with pygame==2.6.1 python -m weight_space.viewer --demo runs/astra-fable-demo-02 --paused
```

Press Space to play or pause. Press 1 for game 1, 2 for game 2, E for the edit
summary, or R to restart. Arrow keys change playback speed. Escape closes the
viewer. The viewer replays recorded states at game speed; it does not make model
calls. It shows each submitted explanation and changed-parameter count, not the
model's private reasoning or a live token stream.

Each game has a 30-second limit by default. Use `--max-steps` on the demo command
to change it. Feedback includes action counts, one state per simulated second,
all damage steps, and the final result. It also includes full-precision layer
pre-activations, post-activations, and action scores at the start, after one second,
every five seconds, on damage, and at the end. Both agents receive the same
activation samples for both original networks. Full state traces remain in the match folders.
Raw replies and provider metadata are saved. Invalid submissions stop the demo;
there is no automatic retry, model fallback, or host execution of returned code.

Astra–Fable uses the CLI subscriptions. To use Tinfoil for Kimi, set
`--pairing astra-kimi` and load the key with `uv run --env-file .env`.
These provider calls do not stream progress. An outstanding request does not
prove that the model is still thinking. A timeout is recorded as a failure.

Inspect activations for any chosen observation with:

```sh
uv run python -m weight_space probe path/to/model.json --inputs 0 1
```

Supply the exact number of inputs for the model: two for XOR or 31 for Street
Fighter. `forward(model, inputs, return_trace=True)` provides the same data in Python.

See `Street_Fighter/LICENSE` and `Street_Fighter/UPSTREAM_LICENSE.md` for license
notices.

## Provider references

- [Codex commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- [Claude Code CLI](https://code.claude.com/docs/en/cli-reference)
- [Tinfoil Python SDK](https://docs.tinfoil.sh/sdk/python-sdk)
- [Tinfoil model list](https://inference.tinfoil.sh/v1/models)
