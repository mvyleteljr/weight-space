/* Report observable progress; a pending request does not prove model activity. */
function agentProgress(agent, phase, now = Date.now()/1000) {
  if (phase === 'ready') return 'Initial policy ready';
  if (phase === 'playing') return 'Playing';
  if (phase === 'awaiting_approval') return 'Paused · user approval required';
  if (['stopped', 'complete', 'failed'].includes(phase)) {
    return phase === 'complete' ? 'Finished' : phase === 'failed' ? 'Failed' : 'Stopped';
  }
  const age = timestamp => Math.max(0, Math.floor(now - timestamp));
  switch (agent.status) {
    case 'request_pending': {
      const seconds = agent.request_started_at ? age(agent.request_started_at) : 0;
      const limit = Math.ceil(agent.reply_timeout || 120);
      return `${seconds >= limit ? 'Overdue' : 'Waiting'} · ${seconds}s / ${limit}s`;
    }
    case 'running_tools':
      return 'Applying update';
    case 'submitted': return 'Ready';
    case 'update_rejected': return 'Invalid update · keeping previous policy';
    case 'kept_previous': return 'Update timed out · keeping previous policy';
    case 'failed': return `Agent failed${agent.error ? ': '+agent.error : ''}`;
    case 'stopped': return 'Stopped';
    default: return 'Queued for update';
  }
}
function trainingProgress(demo) {
  if (demo.phase === 'awaiting_approval') return 'Training paused: an agent requested an environment change. Review context requests below; approval required.';
  if (demo.phase === 'stopped') return 'Training stopped.';
  if (demo.phase === 'ready') return 'Policies ready. Press Start.';
  if (demo.phase === 'playing') return `Game ${demo.viewing_game} in progress.`;
  if (demo.phase === 'complete') return 'Training complete.';
  if (demo.phase === 'failed') return `Training failed: ${demo.error || 'See agent status.'}`;
  if (demo.phase === 'preparing_agents') return 'Before game 1: agents are initializing policies.';
  if (demo.phase === 'editing') return `Game ${demo.editing_after_game} finished. Waiting for agent updates before the next game.`;
  if (demo.phase === 'rematch') return 'Running the next game with updated policies.';
  return 'Preparing training and the first game.';
}
if (typeof module !== 'undefined') module.exports = {agentProgress, trainingProgress};
