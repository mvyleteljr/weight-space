# Model contract

## Current submission format

Only dense JSON models are accepted for inference. Agent-written Python is
prohibited. The runner must not import, execute, compile for execution, or
otherwise run submitted source. The old code-bundle worker is disabled with no
option to enable it. Historical bundles may be read and hashed as inert data.

A model contains exactly `version`, `input_size`, and `layers`. Version is 1.
Each layer contains exactly `weights`, `bias`, and `activation`. Weights are a
matrix with one row per output neuron. Bias is a vector with one value per output.
Activations are limited to `linear`, `relu`, and `tanh`. The trusted runner
implements each operation directly. It never resolves a model-supplied symbol
as a Python object or imports a model-supplied path.

All parameters must be finite numbers. Booleans, expressions, strings, unknown
fields, and inconsistent shapes are rejected. The current limits are 32 layers,
100,000 parameters, and an 8 MB model file. Source code, dynamic imports, external
callbacks, subprocesses, and executable object serialization are not supported.

## Experiment rules

- Create new parameters from scratch. Do not use pretrained weights.
- Set and change weights and biases directly through reasoning.
- Do not train, compute weight gradients, use an optimizer, or run automated
  parameter search.
- Use the trusted task adapter for observation encoding and output decoding.
  Do not add a separate game strategy outside the network.
- Submit all model data before a game. Keep it fixed during the game.
- Change architecture data and weights only between rounds.
- Save each tested model and its result. Do not overwrite a past evaluation.
- Give agents the same completed-game feedback. Do not expose another agent's
  pending changes.
- Do not run agent-written editing or initialization scripts on the host.
  Agents return model data; trusted code writes the files.

The runner can check accepted operations, shapes, and parameter values. These
checks cannot prove how an agent chose its weights. The no-training rule still
requires review of the agent process.

## Future architecture support

The previous `load`, `act`, `save`, and `reset` interface remains a useful design
for trusted model adapters. Agents must not implement these methods as executable
host code. The current dense evaluator has no recurrent state.

A future graph format can describe connections, named tensors, and approved
operations as data. The runner must validate graph size, shapes, operation cost,
and state limits before inference. Every operation must come from a fixed,
trusted implementation. A graph must not contain executable expressions or
custom operator code. This graph format is not implemented yet.

If arbitrary source execution is needed later, run it in a separate disposable
VM with no host mounts, credentials, or network access and with resource limits.
Do not treat a Python import filter or a child process as that isolation boundary.

## Game status

Street Fighter now has a shared fixed-step engine for human controls and model
matches. Its dense model interface has 33 inputs and 18 action scores. Models
are copied before a match and remain fixed during it. See the
[game interface](game-interface.md) for observations, actions, reset, results,
and saved feedback. XOR remains the task for the separate agent `run` command.
