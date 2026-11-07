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

The host sends a compact JSON tool list through each subscription CLI. It accepts
only the listed data operations. Native shell and code tools remain disabled.
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
