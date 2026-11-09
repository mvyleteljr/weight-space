const assert = require('node:assert/strict');
const {agentProgress, trainingProgress} = require('../streaming/web/status.js');
const pending = {status:'request_pending', request_started_at:100, reply_timeout:60, turn:2};
assert.match(agentProgress(pending, 'editing', 120), /Waiting · 20s \/ 60s/);
assert.match(agentProgress(pending, 'editing', 170), /Overdue/);
assert.equal(agentProgress(pending, 'stopped', 170), 'Stopped');
assert.equal(agentProgress({status:'submitted'}, 'editing'), 'Ready');
assert.match(agentProgress({status:'kept_previous'}, 'editing'), /keeping previous policy/);
assert.equal(agentProgress({status:'running_tools'}, 'editing'), 'Applying update');
assert.match(trainingProgress({phase:'editing', editing_after_game:3}), /Game 3 finished/);
assert.match(trainingProgress({phase:'stopped'}), /Training stopped/);
console.log('Progress status tests passed.');

assert.match(agentProgress(pending, 'awaiting_approval'), /approval required/);
assert.match(trainingProgress({phase:'awaiting_approval'}), /approval/i);

assert.match(trainingProgress({phase:'ready'}), /Press Start/);
assert.equal(agentProgress({},'ready'),'Initial policy ready');
assert.equal(agentProgress({},'playing'),'Playing');
assert.equal(trainingProgress({phase:'playing',viewing_game:2}),'Game 2 in progress.');

assert.doesNotMatch(agentProgress(pending, 'editing',120), /reply 2|retry/);
