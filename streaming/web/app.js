const $ = id => document.getElementById(id);
const canvas = $('arena'), ctx = canvas.getContext('2d');
const gameAudio = new GameAudio();
const refreshNetworkTooltip = attachNetworkTooltips($('replies'));
let idleState = null, demo = null, replay = null, selected = 1, frame = 0, playing = false, speed = 1;
let requestId = 0, lastTime = 0, endWait = 0, assets = null, replyKey = '', polling = false;
let policyData = null;
let autoMode = false, autoLoading = false, autoSession = null, autoTally = null, trainingView = null;
let autoPolicyVersion = 0, autoAppliedPolicyVersion = 0;
let activityViews = [];
const historySelection = [null, null];
let activeRun = null, runToken = null, launching = false, canStart = false, generation = 0;
let acknowledged = 0, acknowledging = false, ackRetryAt = 0;
function resetRun(name) {
  stopAutoplay();
  gameAudio.reset();
  activeRun = name; ++requestId; replay = null; selected = 1;
  frame = 0; endWait = 0; playing = false; replyKey = '';
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  $('replies').replaceChildren();
  historySelection.fill(null); policyData = null; activityViews = [];
  acknowledged = 0; acknowledging = false; ackRetryAt = 0;

}
function updateTally() {
  const tally = (autoMode && autoTally) || demo.tally || {wins:[0, 0], draws:0, games:demo.games.length};
  if (!demo.tally) for (const game of demo.games) {
    if (game.result.winner == null) tally.draws++;
    else tally.wins[(game.player_agents || [1, 2])[game.result.winner - 1] - 1]++;
  }
  [0, 1].forEach(i => {
    $(`score-name-${i + 1}`).textContent = demo.agents[i]?.name || ['Astra', 'Opus 5.5'][i];
    $(`score-${i + 1}`).textContent = tally.wins[i];
  });
  $('tally-note').textContent = `${autoMode ? 'Autoplay · ' : ''}${tally.games} game${tally.games === 1 ? '' : 's'} · ${tally.draws} draw${tally.draws === 1 ? '' : 's'}`;
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function get(url) {
  const response = await fetch(url, {cache:'no-store', signal:AbortSignal.timeout(8000)});
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}
function names() {
  return (replay?.player_agents || demo?.next_player_agents || [1, 2]).map(id => demo?.agents[id - 1]?.name || `Player ${id}`);
}
function syncControls() {
  const phase = demo?.phase;
  const initializing = !phase || ['initializing', 'preparing_agents'].includes(phase);
  const active = ['playing','editing','rematch'].includes(phase);
  $('start').textContent = initializing ? 'Initializing…' : active && !demo?.paused ? 'Pause training' : 'Start training';
  $('start').disabled = launching || (!active && !(['ready','complete'].includes(phase) && canStart));
  $('reset').disabled = launching || !runToken;
  $('autoplay').textContent = autoMode ? 'Stop autoplay' : 'Start autoplay';
  $('autoplay').disabled = launching || (!autoMode && !(phase === 'complete' || (demo?.paused && active)));
  $('autoplay').setAttribute('aria-pressed', String(autoMode));
  $('mute').textContent = gameAudio.muted ? 'Unmute' : 'Mute';
  $('mute').setAttribute('aria-pressed', String(gameAudio.muted));
  $('mute').disabled = speed !== 1 || !!gameAudio.error;
  $('mute').title = speed !== 1 ? 'Audio is available at 1× speed' : gameAudio.error;
}
async function post(path, body = {}) {
  const response = await fetch(path, {method:'POST',
    headers:{'Content-Type':'application/json', 'X-Run-Token':runToken},
    body:JSON.stringify(body), signal:AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}
function stopAutoplay() {
  if (!autoMode) return;
  if (autoSession) releaseAutoplay(autoSession);
  ++requestId;
  autoMode = false; autoLoading = false; autoSession = null; autoTally = null;
  autoPolicyVersion = autoAppliedPolicyVersion = 0;
  historySelection.fill(null);
  gameAudio.stop();
  if (trainingView) {
    ({replay, selected, frame, endWait, playing} = trainingView);
    if (replay) gameAudio.load(replay.audio_url);
  }
  trainingView = null; replyKey = '';
  if (policyData) renderPolicies(policyData);
  if (demo) updateTally();
  draw();
  syncControls();
}
function releaseAutoplay(session) {
  // Session-scoped cleanup cannot stop a newer Start autoplay request.
  return post('/api/autoplay-stop', {session}).catch(error => {
    $('status').textContent = error.message;
  });
}
async function autoplayGame() {
  if (autoLoading || launching || !(demo?.paused || demo?.phase === 'complete')) return;
  if (!autoMode) {
    trainingView = {replay, selected, frame, endWait, playing};
    autoMode = true; autoTally = {wins:[0,0],draws:0,games:0};
    historySelection.fill(null);
    autoPolicyVersion = autoAppliedPolicyVersion = 0;
  }
  autoLoading = true; playing = false; gameAudio.stop(); syncControls();
  const token = ++requestId;
  const policyVersion = autoPolicyVersion;
  const changingPolicies = autoSession && policyVersion !== autoAppliedPolicyVersion;
  try {
    const result = await post(changingPolicies ? '/api/autoplay-policies' : autoSession ? '/api/autoplay-next' : '/api/autoplay',
      autoSession ? {session:autoSession, after:selected, ...(changingPolicies ? {policies:[...historySelection]} : {})} : {});
    if (token !== requestId || !autoMode) { releaseAutoplay(result.session); return; }
    autoSession = result.session; selected = result.game.number;
    autoAppliedPolicyVersion = policyVersion;
    if (policyVersion !== autoPolicyVersion) return;
    await gameAudio.load(result.game.audio_url);
    if (token !== requestId || !autoMode) return;
    if (policyVersion !== autoPolicyVersion) return;
    autoTally = result.tally;
    replay = result.game; selected = replay.number; frame = 0; endWait = 0; playing = true;
    replyKey = ''; if (policyData) renderPolicies(policyData);
    updateTally(); draw();
  } catch (error) {
    if (token === requestId) { stopAutoplay(); updateTally(); if (policyData) renderPolicies(policyData); draw(); $('status').textContent = error.message; }
  } finally {
    if (token === requestId) autoLoading = false;
    if (token === requestId && policyData) renderPolicies(policyData);
    syncControls();
    if (token === requestId && autoMode && autoPolicyVersion !== autoAppliedPolicyVersion) autoplayGame();
  }
}
function selectPolicy(agentIndex, snapshotId) {
  historySelection[agentIndex] = snapshotId;
  if (autoMode) {
    ++autoPolicyVersion;
    playing = false; gameAudio.stop();
    autoplayGame();
  }
  if (policyData) renderPolicies(policyData);
}
async function finishGame() {
  if (acknowledging || acknowledged >= selected || Date.now() < ackRetryAt) return;
  const version = generation, run = activeRun, number = selected;
  acknowledging = true;
  try {
    await post('/api/game-finished', {run, game:number});
    if (version === generation) acknowledged = number;
  } catch (error) {
    if (version === generation) {
      ackRetryAt = Date.now() + 2000;
      $('status').textContent = 'Connection interrupted · retrying';
    }
  } finally { if (version === generation) acknowledging = false; }
}
async function selectGame(number, autoplay = false) {
  const token = ++requestId;
  playing = false; syncControls(); $('status').textContent = `Loading game ${number}…`;
  gameAudio.stop();
  try {
    const data = await get(`/api/games/${number}`);
    if (token !== requestId) return;
    await gameAudio.load(data.audio_url);
    if (token !== requestId) return;
    replay = data; selected = number; frame = 0; endWait = 0; playing = autoplay;
    replyKey = ''; if (policyData) renderPolicies(policyData);
    syncControls(); draw();
  } catch (error) { if (token === requestId) { playing = autoplay; endWait = 0; syncControls(); $('status').textContent = error.message; } }
}
function draw() {
  if (!assets || (!replay && !idleState)) return;
  const index = replay ? Math.min(replay.frames.length, Math.floor(frame)) : 0;
  const state = index ? replay.frames[index - 1] : (replay?.initial_state || idleState);
  updatePolicyActivity(index);
  // The DOM image behind the transparent canvas plays APNG frames natively.
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (const cube of state.powerups || []) {
    if (!cube.available) continue;
    ctx.fillStyle = cube.player === 1 ? '#46bee6' : '#d773e6';
    ctx.fillRect(cube.x, cube.y, cube.size, cube.size);
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
    ctx.strokeRect(cube.x+1, cube.y+1, cube.size-2, cube.size-2);
    ctx.fillStyle = '#fff'; ctx.fillRect(cube.x+cube.size/2-2,cube.y+8,4,cube.size-16);
    ctx.fillRect(cube.x+8,cube.y+cube.size/2-2,cube.size-16,4);
  }
  [1, 0].forEach(i => {
    const fighter = state.fighters[i];
    // Keep Grimes at her existing world size with the new 500px source frames.
    const size = 500, scale = i ? 1.5 : 648 / 500;
    const offset = i ? [224, 194] : [144 * 500 / 324, 92 * 500 / 324];
    const width = size * scale, x = fighter.x - offset[0] * scale, y = fighter.y - offset[1] * scale;
    ctx.save(); ctx.translate(x + (fighter.flip ? width : 0), y); ctx.scale(fighter.flip ? -1 : 1, 1);
    ctx.drawImage(assets[i + 1], fighter.frame_index * size, fighter.action * size, size, size, 0, 0, width, width);
    ctx.restore();
    const left = i ? 666 : 24;
    ctx.fillStyle = '#23232d'; ctx.fillRect(left, 52, 310, 20);
    ctx.fillStyle = i ? '#d773e6' : '#46bee6'; ctx.fillRect(left, 52, 310 * fighter.health / 100, 20);
    ctx.fillStyle = '#fff'; ctx.font = 'bold 24px Arial'; ctx.fillText(`${i === 0 ? 'Grimes' : 'Shoggoth'} (${names()[i]})`, left, 38, 310);
    ctx.font = '18px Arial'; ctx.fillText(`HP ${fighter.health}${fighter.damage_dealt == null ? '' : `   DMG ${fighter.damage_dealt}`}`, left, 98);
  });
  ctx.fillStyle = '#fff'; ctx.font = 'bold 28px Arial';
  ctx.fillText(`${Math.max(0, (state.max_steps - state.step) / (replay?.fps || 60)).toFixed(1)}s`, 455, 45);
  if (state.done && state.ending_complete !== false) {
    ctx.textAlign = 'center';
    ctx.fillText(state.winner ? `${names()[state.winner - 1]} wins` : 'Draw', 500, 145);
    ctx.textAlign = 'left';
  }
}

function updatePolicyActivity(index) {
  for (const view of activityViews) {
    if (!view.live) continue;
    const sample = decisionAtFrame(replay, index, view.slot);
    if (sample === view.previous) continue;
    view.previous = sample;
    view.svg.updateActivity(sample);
  }
  refreshNetworkTooltip();
}
function animate(now) {
  const dt = lastTime ? Math.min((now - lastTime) / 1000, 0.1) : 0; lastTime = now;
  if (replay && playing && (autoMode || !demo?.paused)) {
    frame = Math.min(replay.frames.length, frame + dt * replay.fps * speed);
    if (frame >= replay.frames.length) {
      endWait += dt;
      if (autoMode && endWait >= 0.5) autoplayGame();
      if (!autoMode && endWait >= 0.5 && demo?.phase === 'playing' && demo.viewing_game === selected) finishGame();
      if (!autoMode && demo?.games.some(game => game.number === selected + 1)) selectGame(selected + 1, true);
    }
    draw();
  }
  gameAudio.sync(frame / (replay?.fps || 60), !!replay && playing && (autoMode || !demo?.paused) && !document.hidden, speed);
  requestAnimationFrame(animate);
}

function renderPolicies(data) {
  policyData = data;
  const liveGame = !!replay?.networks && (autoMode || (demo?.phase === 'playing' && demo.viewing_game === selected));
  const key = JSON.stringify([data, historySelection, liveGame, replay?.number, autoLoading]); if (key === replyKey) { document.querySelectorAll('.reply-card-top .badge').forEach((badge,i) => { badge.textContent = autoMode ? 'Autoplay' : agentProgress(data.agents[i].agent, demo?.phase); }); return; } replyKey = key;
  activityViews = [];
  const cards = data.agents.map(({agent, snapshots, context_requests = []}, agentIndex) => {
    const card = element('article', undefined, 'reply-card');
    const top = element('div', undefined, 'reply-card-top');
    const heading = element('div', undefined, 'reply-heading');
    heading.append(element('h3', agent.name));
    top.append(heading, element('span', autoMode ? 'Autoplay' : agentProgress(agent, demo?.phase), 'badge'));
    card.append(top);
    if (!snapshots.length) { card.append(element('p', 'Waiting for the first policy…')); return card; }
    const slot = policySlot(replay, agentIndex);
    // An agent's current autoplay model stays pinned while the other agent's
    // selection loads, even if a pending training reply has added newer history.
    const live = liveGame && slot >= 0 && (autoMode ? !!replay.policy_selections &&
      replay.policy_selections[agentIndex] === historySelection[agentIndex] : historySelection[agentIndex] === null);
    let index = historySelection[agentIndex] === null ?
      (autoMode && live ? snapshots.findLastIndex(s => s.architecture.sha256 === replay.networks[slot].sha256) : snapshots.length - 1) :
      snapshots.findIndex(s => s.id === historySelection[agentIndex]);
    if (index < 0) index = snapshots.length - 1;
    const snapshot = snapshots[index];
    const arch = live ? replay.networks[slot] : snapshot.architecture;
    const nav = element('div', undefined, 'policy-nav');
    const previous = element('button', '←'), next = element('button', '→');
    previous.setAttribute('aria-label', `${agent.name}: previous policy update`);
    next.setAttribute('aria-label', `${agent.name}: next policy update`);
    previous.disabled = index === 0; next.disabled = index === snapshots.length - 1;
    previous.onclick = () => selectPolicy(agentIndex, snapshots[index-1].id);
    next.onclick = () => selectPolicy(agentIndex, index+1 === snapshots.length-1 ? null : snapshots[index+1].id);
    const gameNumber = !autoMode && historySelection[agentIndex] === null ?
      (live ? selected : demo?.tally?.games ?? demo?.games?.length ?? snapshot.after_game) : snapshot.after_game;
    nav.append(previous, next, element('span', `game ${gameNumber}`, 'policy-game'));
    heading.append(nav);
    const diagram = element('div', undefined, 'policy-diagram'), svg = architectureDiagram(arch);
    diagram.append(svg); card.append(diagram);
    activityViews.push({svg, slot, live, previous:undefined});
    const log = element('div', undefined, 'reply-log'); log.tabIndex = 0;
    log.setAttribute('aria-label', `${agent.name} public notes for selected update`);
    log.append(element('p', snapshot.note));
    for (const call of snapshot.calls) {
      let detail = call.tool.replaceAll('_', ' ');
      if (!call.done) detail += ' · requested';
      if (call.updates) detail += ` · ${call.updates} values set`;
      if (call.tests?.length) {
        const checked = call.tests.filter(t => t.matches_expected !== null);
        detail += ` · ${call.tests.length} inputs · ${checked.filter(t => t.matches_expected).length}/${checked.length} expectations matched`;
      }
      log.append(element('p', detail, 'tool'));
      if (call.reason) log.append(element('p', call.reason, 'tool-reason'));
      if (call.error) log.append(element('p', call.error, 'error'));
    }
    if (historySelection[agentIndex] === null && agent.error) log.append(element('p', agent.error, 'error'));
    card.append(log);
    if (context_requests.length) {
      const requests = element('details', undefined, 'context-requests');
      requests.open = true;
      requests.append(element('summary', `Context requests (${context_requests.length})`));
      for (const request of context_requests) {
        const item = element('div', undefined, 'context-request');
        item.append(element('span', `After game ${request.after_game} · ${request.status === "awaiting_approval" ? "approval required" : "requested"}`, 'reply-meta'),
          element('p', request.request), element('p', request.reason, 'tool-reason'));
        requests.append(item);
      }
      card.append(requests);
    }
    return card;
  });
  $('replies').replaceChildren(...cards);
  updatePolicyActivity(replay ? Math.min(replay.frames.length,Math.floor(frame)) : 0);
}
async function poll() {
  if (polling || launching) return; polling = true;
  const version = generation;
  try {
    const data = await get('/api/run');
    if (version !== generation) return;
    if (data.run !== activeRun) resetRun(data.run);
    runToken = data.run_token;
    canStart = data.can_start;
    idleState = data.initial_state || idleState;
    demo = data.demo;
    if (autoMode && !demo?.paused && demo?.phase !== 'complete') stopAutoplay();
    if (!demo) { $('status').textContent = 'No training session'; return; }
    updateTally();
    $('status').textContent = demo.phase === 'playing' ? `Game ${demo.viewing_game}` :
      demo.phase === 'ready' ? 'Ready' : ['initializing','preparing_agents'].includes(demo.phase) ? 'Initializing policies' :
      demo.phase === 'editing' ? 'Waiting for agents' : demo.phase.replaceAll('_', ' ');
    if (demo.paused) $('status').textContent = 'Paused';
    const policies = await get('/api/policy-history');
    if (version !== generation) return;
    renderPolicies(policies);
    if (demo.phase === 'stopped') playing = false;
    if (!autoMode && demo.phase === 'playing' && demo.viewing_game !== selected) await selectGame(demo.viewing_game, true);
    else if (!autoMode && !replay && demo.phase !== 'stopped' && demo.games.length) await selectGame(demo.viewing_game || 1, demo.phase === 'playing');
    syncControls(); draw();
  } catch (error) {
    if (version !== generation) return;
    $('status').textContent = 'Connection interrupted · retrying';
  } finally { polling = false; }
}
async function control(path) {
  if (launching || !runToken) return;
  if (path !== '/api/pause') stopAutoplay();
  launching = true; ++generation; ++requestId;
  playing = false; syncControls();
  try {
    const data = await post(path);
    if (path === '/api/reset') { resetRun(data.run); demo = null; }
    else if (path === '/api/pause' || path === '/api/resume') { demo.paused = path === '/api/pause'; playing = true; }
    else { canStart = false; demo.phase = 'rematch'; }
  } catch (error) {
    $('status').textContent = error.message;
  } finally { launching = false; syncControls(); poll(); }
}
$('start').addEventListener('click', () => {gameAudio.unlock(); control(demo?.phase === 'complete' || demo?.phase === 'ready' ? '/api/runs' : demo?.paused ? '/api/resume' : '/api/pause');});
$('autoplay').addEventListener('click', () => {
  if (autoMode) stopAutoplay();
  else {gameAudio.unlock(); autoplayGame();}
});
$('mute').addEventListener('click', () => {gameAudio.muted = !gameAudio.muted; gameAudio.unlock(); syncControls();});
$('reset').addEventListener('click', () => control('/api/reset'));
$('speed').addEventListener('change', () => {speed = Number($('speed').value); syncControls();});
document.addEventListener('visibilitychange', () => {if (document.hidden) gameAudio.stop();});
Promise.all(['/assets/background.jpg', '/assets/grimes-sprites-large.png', '/assets/shoggoth-sprites-large.png'].map(src => new Promise((resolve, reject) => {
  const image = new Image(); image.onload = () => resolve(image); image.onerror = reject; image.src = src;
}))).then(images => {assets = images; $('background').src = images[0].src; draw();}).catch(() => {$('status').textContent = 'Game images could not load.';});
poll(); setInterval(poll, 1500); requestAnimationFrame(animate);
