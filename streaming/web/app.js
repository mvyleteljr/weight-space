const $ = id => document.getElementById(id);
const canvas = $('arena'), ctx = canvas.getContext('2d');
let idleState = null, demo = null, replay = null, selected = 1, frame = 0, playing = false, speed = 1;
let requestId = 0, lastTime = 0, endWait = 0, assets = null, replyKey = '', polling = false;
let policyData = null;
const historySelection = [null, null];
let activeRun = null, runToken = null, launching = false, canStart = false, generation = 0;
let acknowledged = 0, acknowledging = false, ackRetryAt = 0;
function resetRun(name) {
  activeRun = name; ++requestId; replay = null; selected = 1;
  frame = 0; endWait = 0; playing = false; replyKey = '';
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  $('replies').replaceChildren();
  historySelection.fill(null); policyData = null;
  acknowledged = 0; acknowledging = false; ackRetryAt = 0;

}
function updateTally() {
  const tally = demo.tally || {wins:[0, 0], draws:0, games:demo.games.length};
  if (!demo.tally) for (const game of demo.games) {
    if (game.result.winner == null) tally.draws++;
    else tally.wins[(game.player_agents || [1, 2])[game.result.winner - 1] - 1]++;
  }
  [0, 1].forEach(i => {
    $(`score-name-${i + 1}`).textContent = demo.agents[i]?.name || ['Astra', 'Opus 5.5'][i];
    $(`score-${i + 1}`).textContent = tally.wins[i];
  });
  $('tally-note').textContent = `${tally.games} game${tally.games === 1 ? '' : 's'} · ${tally.draws} draw${tally.draws === 1 ? '' : 's'}`;
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
  $('start').textContent = initializing ? 'Initializing…' : active && !demo?.paused ? 'Pause' : 'Play';
  $('start').disabled = launching || (!active && !(phase === 'ready' && canStart));
  $('reset').disabled = launching || !runToken;
}
async function post(path, body = {}) {
  const response = await fetch(path, {method:'POST',
    headers:{'Content-Type':'application/json', 'X-Run-Token':runToken},
    body:JSON.stringify(body), signal:AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
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
  try {
    const data = await get(`/api/games/${number}`);
    if (token !== requestId) return;
    replay = data; selected = number; frame = 0; endWait = 0; playing = autoplay;
    syncControls(); draw();
  } catch (error) { if (token === requestId) { playing = autoplay; endWait = 0; syncControls(); $('status').textContent = error.message; } }
}
function draw() {
  if (!assets || (!replay && !idleState)) return;
  const index = replay ? Math.min(replay.frames.length, Math.floor(frame)) : 0;
  const state = index ? replay.frames[index - 1] : (replay?.initial_state || idleState);
  ctx.drawImage(assets[0], 0, 0, 1000, 600);
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
    ctx.font = '18px Arial'; ctx.fillText(`HP ${fighter.health}`, left, 98);
  });
  ctx.fillStyle = '#fff'; ctx.font = 'bold 28px Arial';
  ctx.fillText(`${Math.max(0, (state.max_steps - state.step) / (replay?.fps || 60)).toFixed(1)}s`, 455, 45);
  if (state.done && state.ending_complete !== false) {
    ctx.textAlign = 'center';
    ctx.fillText(state.winner ? `${names()[state.winner - 1]} wins` : 'Draw', 500, 145);
    ctx.textAlign = 'left';
  }
}
function animate(now) {
  const dt = lastTime ? Math.min((now - lastTime) / 1000, 0.1) : 0; lastTime = now;
  if (replay && playing && !demo?.paused) {
    frame = Math.min(replay.frames.length, frame + dt * replay.fps * speed);
    if (frame >= replay.frames.length) {
      endWait += dt;
      if (endWait >= 0.5 && demo?.phase === 'playing' && demo.viewing_game === selected) finishGame();
      if (demo?.games.some(game => game.number === selected + 1)) selectGame(selected + 1, true);
    }
    draw();
  }
  requestAnimationFrame(animate);
}

function renderPolicies(data) {
  policyData = data;
  const key = JSON.stringify([data, historySelection]); if (key === replyKey) { document.querySelectorAll('.reply-card-top .badge').forEach((badge,i) => { badge.textContent = agentProgress(data.agents[i].agent, demo?.phase); }); return; } replyKey = key;
  const cards = data.agents.map(({agent, snapshots, context_requests = []}, agentIndex) => {
    const card = element('article', undefined, 'reply-card');
    const top = element('div', undefined, 'reply-card-top');
    top.append(element('h3', agent.name), element('span', agentProgress(agent, demo?.phase), 'badge'));
    card.append(top);
    if (!snapshots.length) { card.append(element('p', 'Waiting for the first policy…')); return card; }
    let index = historySelection[agentIndex] === null ? snapshots.length - 1 : snapshots.findIndex(s => s.id === historySelection[agentIndex]);
    if (index < 0) index = snapshots.length - 1;
    const snapshot = snapshots[index], arch = snapshot.architecture;
    const nav = element('div', undefined, 'policy-nav');
    const previous = element('button', '←'), next = element('button', '→');
    previous.setAttribute('aria-label', `${agent.name}: previous policy update`);
    next.setAttribute('aria-label', `${agent.name}: next policy update`);
    previous.disabled = index === 0; next.disabled = index === snapshots.length - 1;
    previous.onclick = () => {historySelection[agentIndex] = snapshots[index-1].id; renderPolicies(policyData);};
    next.onclick = () => {historySelection[agentIndex] = index+1 === snapshots.length-1 ? null : snapshots[index+1].id; renderPolicies(policyData);};
    nav.append(previous, next);
    card.append(nav, element('p', `${snapshot.after_game === 0 ? 'Before game 1' : `After game ${snapshot.after_game}`} · ${snapshot.stage}`, 'reply-meta'));
    const diagram = element('div', undefined, 'policy-diagram'); diagram.append(architectureDiagram(arch)); card.append(diagram);
    card.append(element('p', 'Select a neuron · hover a connection for its weight', 'network-legend'));
    card.append(element('p', `${arch.parameters.toLocaleString()} parameters · ${arch.memory_size} memory values`, 'policy-stats'));
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
    if (!replay && demo.phase !== 'stopped' && demo.games.length) await selectGame(demo.viewing_game || 1, true);
    syncControls(); draw();
  } catch (error) {
    if (version !== generation) return;
    $('status').textContent = 'Connection interrupted · retrying';
  } finally { polling = false; }
}
async function control(path) {
  if (launching || !runToken) return;
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
$('start').addEventListener('click', () => control(demo?.paused ? '/api/resume' : demo?.phase === 'ready' ? '/api/runs' : '/api/pause'));
$('reset').addEventListener('click', () => control('/api/reset'));
$('speed').addEventListener('change', () => {speed = Number($('speed').value);});
Promise.all(['/assets/background.jpg', '/assets/grimes-sprites-large.png', '/assets/shoggoth-sprites-large.png'].map(src => new Promise((resolve, reject) => {
  const image = new Image(); image.onload = () => resolve(image); image.onerror = reject; image.src = src;
}))).then(images => {assets = images; draw();}).catch(() => {$('status').textContent = 'Game images could not load.';});
poll(); setInterval(poll, 1500); requestAnimationFrame(animate);
