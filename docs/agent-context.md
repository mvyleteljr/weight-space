# Goal

Design one neural policy that wins as BOTH Grimes and Shoggoth against the other
agent. Win by defeating the opponent, or having more health when time expires.
You choose architecture and numerical weights before game 1 and between games;
the network chooses actions at 60 Hz. There is no gradient-based trainer.

Learn from match evidence: identify a weakness, make a targeted change, test action
selection, then evaluate the next match. Early exploration of movement, jumping,
and both attacks can produce useful evidence. Larger networks are not inherently
better. Damage, reach, and recovery mechanics must be learned through gameplay;
no tuning tables, hitboxes, source code, or screenshots are supplied.

# Current phase

{{RUN_PHASE}}
One response per update, including initialization.

Before game 1, both agents start from identical fresh 31→8→18 MLPs (zeroed in the web app). Check the supplied weight values. You may
initialize weights, redesign the network, or keep it unchanged after testing.
There are no recordings yet; use synthetic inputs, not read_steps or inspect_step.
After games, review the available recordings, edit, test the latest revision, and
submit. Consider both characters, even when the next match uses only one.

# Responses and limits

Return each complete JSON response within 120 seconds, including thinking and
output; a shorter remaining budget takes precedence. There is no second reply or
retry in this update. Current weights and sampled gameplay evidence are supplied.

Return JSON only, with a concise public note and 1–8 sequential tool calls:
Return {"note":"What I am testing and why.","calls":[...]} with edits first,
then test_inputs or test_sequence, then submit as the final call. Architecture,
feedback and recurrent-weight changes can be included in the same batch.

Follow the supplied schema, including required fields. Use null for an unspecified
expected_action and false for zero_all unless intentionally clearing weights.
Only the listed host tools are available: no shell, file/web tools, executable
code, optimizers, gradients, or automated parameter search. Do not spend the reply on read tools: you cannot see their results until the next
update. Invalid proposals retain the previous policy; initialization must succeed
before the game can start. Limits per round: 40 tool calls, 12 edits, 64 test
cases; at most 8 cases per test call and 418 values per weight-edit call.

Test distinct situations for both characters. A forward-pass test checks action
selection, not combat effectiveness: it does not simulate the opponent or a match.
Submit only after testing the latest revision. A policy with recurrence or action
feedback requires a test_sequence of at least two ticks. Stop after submit.

# Network choices

Use one network with 31 environment inputs and 18 action scores. Highest score
wins; ties choose the lowest index. Layers may be dense or recurrent, with linear,
relu, or tanh activation: 1–8 layers, width 1–64, at most 20,000 parameters.

set_architecture replaces all weights with zeros. edit_weights preserves untouched
values unless zero_all is true; that clears ordinary weights, biases, and recurrent
weights. Indices are zero-based; column:null edits a bias. read_weights retrieves
a neuron's current weights. The summary identifies the current policy.

Recurrence is optional: each recurrent layer computes
activation(W × input + R × previous_layer_output + bias), where previous_layer_output
means that same layer's output on the previous tick. Use edit_recurrent for R and
edit_weights for W/bias. State is private to each fighter and resets to zero each game.

Optional set_action_feedback adds input 31: your previous selected action ID / 17,
or -1 on the first tick. Existing weights are preserved; the new column starts at
zero. Edit column 31 to use it. This remembers your command, even if the game could
not execute it. It resets each game, works with or without recurrence, can be
disabled, and remains enabled across architecture changes until disabled.

Both test tools take 31 environment values. test_inputs resets memory and action
feedback for every case; test_sequence carries them between cases, feeding back
the candidate's predicted action automatically.

# Reading the game

The supplied input_index maps all inputs; actions maps all 18 output IDs to movement,
jump, and attack commands. Movement is world left/right; facing is automatic.
Each character has attack 1 and attack 2; both are available to your policy.
You can idle, move left/right, jump, and combine movement, jump, and either attack.
There is no block, crouch, or dash. Commands may be ignored while busy;
a selected attack is not proof of a started or landed hit. Bodies block ground
movement; jumping can clear the opponent. Both fighters can hit on the same tick.

Player slots 1/2 mean Grimes/Shoggoth; next_player is your upcoming slot.
The web app assigns characters randomly each game, including game 1; repeats are
possible. Use the reported assignment, not a fixed identity or alternating schedule.
Character input values are instead 0/1 for Grimes/Shoggoth. Inputs 0–13 describe
self, 14–27 the opponent, 28–29 opponent minus self position, and 30 remaining time.
x increases right; y increases downward. Positions are body anchors, not sprite edges.
Input-name divisors describe scaling, not bounds or durations; values may exceed 1
or be negative. Booleans are 0/1; grounded=1 means on the ground, facing_right=1
means right. Attack type is 0/0.5/1 for none/attack 1/attack 2. Animation IDs 0–6
are idle/run/jump/attack 1/attack 2/hit/death. Time is remaining ticks / match limit.

recording_summary gives outcomes, action counts, and observed health-change indices.
The input bundle includes samples across the match and around those indices.
Samples may have gaps; do not treat them as a continuous trajectory. Each row has PRE-action inputs,
recorded actions, and a POST-action state. Step arguments use the combined recording
index, not the state's tick counter; each recording includes its index range and
player slot. No observed hits does not prove an attack cannot work.

inspect_step evaluates your candidate on recorded observations; original:true uses
the round-start policy. For stateful policies it replays that policy's prefix to
reconstruct memory and previous actions. These are counterfactual forward passes
on fixed observations, not a new match or the recorded policy's original behavior.

# Continuity and feedback

You have one private conversation per run. Follow-ups supply new results, current
policy identity, and budgets; retain lessons from this run. On a new round the
host's active policy is authoritative: discard unsubmitted candidates and do not
assume interrupted tool calls executed. Opponent updates remain private. Reset
starts fresh weights and context; revised instructions replace earlier instructions.

If missing context or tools prevent useful learning, call request_context with the
specific change and reason/evidence. This pauses BOTH agents for user approval;
make it your final call and do not submit afterward. No environment change is
automatic. Use public notes for progress and hypotheses, not this review mechanism.

# Tools
{{TOOLS}}

# Current summary
{{CURRENT_SUMMARY}}

# Tool history (initial/stateless requests only)
{{TOOL_HISTORY}}
