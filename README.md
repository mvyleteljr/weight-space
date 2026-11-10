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

Human controls and model matches share a fixed-step engine. Models receive 33
state values and return 18 action scores. Run a headless match with:

```sh
uv run python -m weight_space game-spec
uv run python -m weight_space init workspaces/player-1.json --sizes 33 16 18 --seed 1
uv run python -m weight_space init workspaces/player-2.json --sizes 33 16 18 --seed 2
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
For training, run `uv run python -m streaming.server --allow-new-runs --port 8081`.
Every server launch and **Reset** starts both agents from identical zeroed weights
and fresh conversations. The agents initialize their policies before **Start training**
is enabled. Characters are assigned randomly each game. The tally counts agent wins
and draws. Saved `--demo` selections and `WEIGHT_SPACE_DEMO` are ignored in training mode.

Astra and Opus 5.5 receive match results, sampled gameplay evidence, and their
current weights. Each returns one policy proposal; the next game evaluates it.
There are no synthetic test calls or extra model queries within an update.
Both begin with the same 33–8–18 network. Each agent has its own candidate.

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
A timeout or invalid proposal keeps that agent's last submitted policy without
retrying the model. Unsubmitted edits are discarded and the reply card reports
`kept_previous`. Initialization failure prevents the first game from starting.
A timeout message shows the time limit without the full CLI command.

Choose each provider and model with `--player-1 provider:model` and
`--player-2 provider:model`. Providers are `codex`, `claude`, and `tinfoil`.
Use `--reply-timeout 25 --edit-seconds 60` to set time limits in seconds.
Load `.env` when using Tinfoil. Failed updates never replace the active policy
with an unsubmitted revision.

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
allows only the trusted data tools and their argument fields. Claude replies are
read from `structured_output`. Host validation still checks types, bounds, and
state before applying edits. A valid JSON shape does not prove a good strategy.
The game requests one reply per agent at initialization and after each completed
game that has a following game. Current weights and sampled match evidence are
included upfront. The reply contains up to eight ordered architecture/weight edits
and a final `submit`, or an environment-change request. Keeping the current policy
is allowed. Read and synthetic-test tools are excluded from this live protocol;
the next game evaluates the proposal. No retries or follow-up queries occur within
an update. Astra uses medium reasoning effort; Opus 5.5 uses high. Each reply has a
120-second limit. The host validates network dimensions, bounds, and finite values;
invalid proposals never become the next game's policy.

The standalone interactive lab still supports forward-pass tests for development.
Those tests are separate from live training and do not simulate a match.

Each `lab-1` or `lab-2` directory contains prompts, replies, provider metadata,
weight revisions, and `tools.jsonl`. The tool log contains arguments and results.
A match uses the agents' submitted policies. No agent code runs, and no automatic
weight search occurs. Gameplay provides the evidence for the following update.

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
the same random 33–8–18 network. They receive the same game 1 feedback and edit
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

Astra–Opus 5.5 uses the CLI subscriptions. To use Tinfoil for Kimi, set
`--pairing astra-kimi` and load the key with `uv run --env-file .env`.
These provider calls do not stream progress. An outstanding request does not
prove that the model is still thinking. A timeout is recorded as a failure.

Inspect activations for any chosen observation with:

```sh
uv run python -m weight_space probe path/to/model.json --inputs 0 1
```

Supply the exact number of inputs for the model: two for XOR or 33 for Street
Fighter. `forward(model, inputs, return_trace=True)` provides the same data in Python.

See `Street_Fighter/LICENSE` and `Street_Fighter/UPSTREAM_LICENSE.md` for license
notices.

## Provider references

- [Codex commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- [Claude Code CLI](https://code.claude.com/docs/en/cli-reference)
- [Tinfoil Python SDK](https://docs.tinfoil.sh/sdk/python-sdk)
- [Tinfoil model list](https://inference.tinfoil.sh/v1/models)

### Timed autonomous training

The CLI and browser New run launcher default to 10 minutes of repeated matches
and private weight editing. Each agent carries its submitted weights forward.
The wall-clock budget includes matches and editing; pending model calls are
limited by the remaining budget. A final match records the last accepted weights
at the deadline, so shutdown can take a little longer than the budget.

```sh
.venv/bin/python -m weight_space.tool_loop --output runs/timed-training --duration-seconds 600 --swap-sides
```

Add `--resume-from runs/previous-run` to continue the same agents' last played
weights in a new run. Explicit `--games 6` selects the older fixed-game mode
unless `--duration-seconds` is also supplied. Combat tuning is not disclosed to
agents; they infer attack behavior from recorded gameplay.

### Agent-designed policies and history

The tool-loop agents can now change their architecture and weights each editing
round. Each agent has **one policy for both characters**, with 33 inputs and 18
action scores. Architectures support 1–8 dense or simple recurrent layers,
1–64 neurons per layer, linear/ReLU/tanh activations, and at most 20,000
parameters. These are data-only networks, not agent-supplied executable code.

`set_architecture` replaces the candidate with zero weights; `edit_weights`
sets ordinary weights/biases and `edit_recurrent` sets state-to-state weights.
Recurrent layers compute `activation(W x + R h_previous + bias)`. Each policy has
private memory that resets at the beginning of every match, including character
swaps. Recurrent policies can be submitted directly, just like MLPs; the next
game evaluates their behavior.
Only submitted candidates become the next game's policy; timeouts retain the
previous policy. Damage/recovery tuning remains hidden from agent instructions.

The spectator page shows compact win totals and gameplay at the top, with
two policy panels below the game. Replays load paused. SVG diagrams show layers, widths, activations, and recurrent loops;
parameter counts and a policy fingerprint identify weight-only revisions too.
Each panel has its own previous/next arrows. Reaching the newest update resumes
automatic following; browsing older updates leaves that panel there. Updates pair
public reply notes and tool outcomes with the policy revision at that point,
and distinguish candidates from submitted or discarded policies. Full matrices
remain in each run's `lab-*/revision-*.json` artifacts.

### Update context and agent requests

Each editing prompt explains indexed inputs and normalization, animation IDs,
character identity versus player slots, pre-action observations versus post-action
results, recurrent resets, and how the next match evaluates the policy proposal. The summary includes agent-relative outcomes, action counts, and
up to 12 observed health-change events with `read_steps` indices. Damage/recovery
configuration stays hidden; gameplay evidence remains accessible.

Agents use `request_context` (requested change + evidence/reason) as their final
call when they need an environment or context change. It stops training before
another match and blocks new training while approval is pending. An in-flight
opponent reply can finish, but no further tools are run after the pause is seen.
Requests persist in `lab-*/context-requests.json` and the run's
`approval-request.json`, and appear in the **Context requests** panels.
The supervising assistant reviews these requests with the user and must obtain
explicit approval before changing the environment. No change is applied automatically.
The saved request does not itself send a chat notification; the assistant must
monitor the run or inspect it on the next interaction.

Network diagrams show every neuron and every feedforward connection. During play,
input values, hidden-layer outputs, and final action logits update with the displayed
game on the exact simulation tick (60 Hz at 1×). Inputs and hidden layers use
absolute magnitude relative to their layer maximum; zeros have black centers.
Action brightness instead scales signed logits from lowest (black) to highest
(white), so a rejected negative score cannot look stronger than the winning score.
The chosen action is larger with a white outline, including ties and all-zero scores.
A short caption distinguishes the requested action from actual horizontal motion:
knockback, body collisions, hit reactions, and recovery can override movement.
Each connection shows its current signal
(source activation × weight), normalized by the largest absolute signal in that
connection layer. Immediate tooltips show input meanings, hidden-neuron values,
action names, or signed connection signals and weights.
These display-only scales never change network calculations or decisions.

The server reconstructs activity from the frozen policies and recorded observations,
advancing recurrent memory and previous-action feedback on every game tick, and
checks every chosen action against the recording. Character swaps map activity to
the correct agent. History views and times without a policy decision show weights
only, with hollow neurons. Gray loops denote recurrent state; they are schematic,
not individual recurrent weights. Wide networks scroll horizontally.

Previous-action feedback is optional: agents call `set_action_feedback` with
`enabled: true` to add input 33. Its value is the previous selected action ID / 17,
or -1 at the start of each game. It records the command selected even when combat
rules prevent it from executing. Existing weights are preserved; the new column
starts at zero. Agents can edit that column or disable feedback. This works with
MLPs and recurrent layers. Stateful policies need no synthetic test before
submission; the next game evaluates them.

Knockouts play all seven death frames before showing the result and releasing the
next agent update. These ending frames are presentation only: they cannot change
health, rewards, or the winner, and are not added to the agents' game evidence.

The training page plays recorded Python game frames. Its synchronized audio track
uses the original music, sword, and magic assets at their original game volumes;
attack sounds follow recorded attack starts. The Python server renders one WAV per
match using FFmpeg, caches it in the run, and serves it over HTTP. Install FFmpeg
on the host to enable audio. **Mute/Unmute** sits in the training toolbar. Audio plays only at
1× and stops on pause, reset, between games, and in a hidden tab. The mute control
is disabled at other speeds; returning to 1× rejoins the displayed game time.
This audio path is for the training page; the separate legacy RTSP broadcaster
still publishes video only.

The web controller has **Start training/Pause training**, **Start autoplay/Stop autoplay**, **Mute**, **Speed**, and **Reset**. Restarting the
server reopens the current run from `runs/.frontend-current.json`, preserving
accepted architectures and weights, scores, games, policy history, prompts, and
model responses. It waits for **Start training** before resuming gameplay.
Each agent receives its own saved conversation on the first update after a
restart, then normal incremental updates. An interrupted match is shown again
without counting its score twice. An interrupted update keeps completed
submissions and the previous policy for any unfinished agent; partial edits are
not applied and the same round is not queried again.

Only the first launch without a saved run, or **Reset**, starts from identical
zeroed 33–8–18 policies with zero scores and no old agent context. Both agents
receive their initial context and can initialize weights or redesign their
network. **Initializing…** is disabled until both submit their first policies.
If initial setup was interrupted, restarting retries only the missing agent and
preserves all earlier responses. **Start training** begins the 10-minute session.
Reset archives the previous run and starts fresh; its logs are not sent to the
new agents. A missing or invalid saved-run pointer produces an error rather than
silently replacing learned policies. Pending environment requests still require
approval; restarting does not bypass them.

Every game appears automatically, in order. Speed changes how fast the game is
shown. The training button becomes **Pause training** while running; **Start training** resumes it. An agent update already underway can finish, but the next game waits for resume. There are no replay, seeking, or game-selection controls. The trainer
waits for the browser to finish each game before updating the agents, so it cannot
skip ahead of the viewer. Closing the page leaves the trainer waiting at that game;
reopening it continues the current game. Reset stops the trainer and its agent
processes, clears the screen and scores, and initializes a new session.

**Start autoplay** is enabled after **Pause training** or when the training time limit is reached. It freezes the accepted
networks at that moment and plays fresh 30-second matches continuously, randomly
assigning the characters each game. It makes no model calls and does not update
weights, training scores, or agent context. Its separate tally is labeled Autoplay;
speed, audio, and live network diagrams still work. An agent request already in
flight when training was paused may finish, but cannot change the frozen autoplay
policies. **Stop autoplay** returns to the paused training frame without resuming training.
**Start training** stops autoplay and returns to the paused training
frame; **Reset** stops it and initializes a fresh training session. Both disable
Autoplay until training is paused again. Only the last two exhibition games are
retained for playback, keeping long sessions bounded. In Autoplay, the existing
history arrows select that agent’s saved network and restart the current matchup
without scoring the interrupted game. Each agent can use a different revision;
changing one leaves the other's frozen network unchanged, including during loading
and character swaps. Each card's game label identifies its policy's training game,
not the autoplay match count. The rightmost position restores its latest network. During training the arrows
only browse history. No training weights are overwritten. After the 10-minute limit,
**Start training** continues the same run for another 10 minutes, retaining its
accepted networks, scores, and game history. The agents receive their own saved
conversation once when the trainer restarts, followed by normal round updates.

Reset clears architecture, weights, recurrent state, action feedback, and agent
context. Each agent gets a fresh private CLI session and temporary working directory.
Old logs stay archived but are never supplied to the new agents. CLI runs remain
randomly initialized unless `--zero-initial` is supplied. `--wait-for-start` and
`--wait-for-viewer` enable the web controller's initialization and game-display gates.

Fresh runs launched from the UI/CLI give both agents an initialization phase before
game 1. They receive no recordings or prior results and can edit weights, change
architecture, enable memory, or keep the initial policy. This
phase uses the same bounded tools and request/approval gate as later updates.
Setup consumes the run's wall-clock budget. A timeout keeps the initial policy;
a failed update or environment-change request prevents gameplay from starting.
Initialization logs are stored in `edit-0/lab-1` and `edit-0/lab-2`.

### Editing agent context

Edit [`docs/agent-context.md`](docs/agent-context.md) to change the goal,
initialization guidance, and operating instructions shared by Astra and Opus 5.5.
The tool loop reads this file for every request, including before game 1; edits
apply to subsequent requests without rebuilding. Keep the `{{...}}` placeholders:
they insert the current phase, reply number, tool definitions, compact run summary,
and tool history. Agents inspect weight values through `read_weights`; the default
prompt does not include full weight arrays. Normal Markdown and braces are safe to edit.
Each lab saves the exact rendered prompt as `turn-N.prompt.txt`. Tool permissions
and network limits are enforced separately in Python; prose changes do not lift them.

### Persistent agent conversations

Astra and Opus 5.5 each receive the full Markdown context once per run. Later replies
send only new tool results and changing budgets/policy metadata. Between games,
the update contains the new match summary and authoritative current-policy identity;
it explicitly discards any unsubmitted candidate from the previous round. The
agents can inspect current weights through tools instead of receiving repeated
weight arrays. If the Markdown changes, the revised instructions are sent once
on the next request. The structured-output schema remains enforced on every call.

Calls resume exact provider session IDs, never `--last` or `--continue`. Sessions
are separate for each agent, and a reset starts new ones. The existing read-only,
no-shell/no-native-tools restrictions remain in effect. Other provider integrations
without CLI session support retain the stateless behavior.

`turn-N.prompt.txt` logs the initial/update payload; `turn-N.attempt-M.prompt.txt`
logs exactly what was sent, including retry notices. Provider JSON and `session.json`
record session identity, resume status, and request counts. A timed-out response's
proposed tools are never executed; retries explicitly state that no tools from
that interrupted response were applied. Missing or mismatched session IDs fail
rather than silently starting a context-free conversation.

The provider CLI manages its conversation context window/compaction. Resuming
reduces the repeated text sent by this application, but does not guarantee reduced
provider billing or unlimited context retention.

The web launcher randomly assigns Grimes and Shoggoth before every game (including
game 1). Each assignment is an independent draw, so repeats are possible. Agent
context, character labels, and scores follow the recorded assignment. The run seed
reproduces assignments. CLI: `--random-sides`; do not combine with `--swap-sides`
or `--paired-games`.

### Animated browser background

Place an animated PNG at `Street_Fighter/assets/images/anthropic-church-animated-1000x600.apng` and reload the
spectator page. The web server prefers it over `bg1.jpg`; remove it to restore
the static background. Use a 1000×600 (5:3) composition. The browser view crops
the bottom 67 pixels, as it does for the existing background.

The background animates as a native browser image beneath the transparent game
canvas. Its timing and loop count come from the APNG: it continues while gameplay
is paused and is independent of the speed selector. This support is for the web
viewer; native Pygame and captured HLS output still use the static background.
