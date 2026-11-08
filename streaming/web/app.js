const $ = id => document.getElementById(id);
const requested = new URLSearchParams(location.search).get('match') || 'match-1';
const match = /^match-[a-zA-Z0-9_-]+$/.test(requested) ? requested : 'match-1';
const canvas = $('arena'), ctx = canvas.getContext('2d');
let demo = null, replay = null, selected = 1, frame = 0, playing = false, speed = 1;
let requestId = 0, lastTime = 0, endWait = 0, fallback = false, assets = null, replyKey = '', polling = false;
const cache = new Map();
let activeRun = null, runToken = null, launching = false, generation = 0;
function resetRun(name) {
  activeRun = name; ++requestId; cache.clear(); replay = null; selected = 1;
  frame = 0; endWait = 0; playing = false; replyKey = '';
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  $('replies').replaceChildren(); $('game').replaceChildren();
  const latest = element('option', 'Latest · follow live'); latest.value = 'latest';
  $('edit-round').replaceChildren(latest);
  $('left-name').textContent = 'Astra'; $('right-name').textContent = 'Fable';
  $('outcome').textContent = 'VS'; $('match-label').textContent = 'NEW RUN';
  $('time').textContent = '0:00 / 0:00'; $('seek').value = 0;
  $('playback-status').textContent = 'Waiting for game 1…';
}
function updateTally() {
  const tally = demo.tally || {wins:[0, 0], draws:0, games:demo.games.length};
  if (!demo.tally) for (const game of demo.games) {
    if (game.result.winner == null) tally.draws++;
    else tally.wins[(game.player_agents || [1, 2])[game.result.winner - 1] - 1]++;
  }
  [0, 1].forEach(i => {
    $(`score-name-${i + 1}`).textContent = demo.agents[i]?.name || ['Astra', 'Fable'][i];
    $(`score-${i + 1}`).textContent = tally.wins[i];
  });
  $('tally-note').textContent = `Run tally · ${tally.games} games complete · ${tally.draws} draws`;
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
function clock(frames) {
  const seconds = Math.floor(frames / (replay?.fps || 60));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function names() {
  return (replay?.player_agents || [1, 2]).map(id => demo?.agents[id - 1]?.name || `Player ${id}`);
}
function syncControls() {
  $('play').textContent = playing ? 'Pause' : 'Play';
  $('play').disabled = $('restart').disabled = $('seek').disabled = !replay;
  $('next').disabled = !demo?.games.some(game => game.number === selected + 1);
  if (replay) {
    $('seek').max = replay.frames.length; $('seek').value = Math.min(replay.frames.length, Math.floor(frame));
    $('time').textContent = `${clock(frame)} / ${clock(replay.frames.length)}`;
  }
}
async function selectGame(number, autoplay = false) {
  const token = ++requestId;
  playing = false; syncControls(); $('playback-status').textContent = `Loading game ${number}…`;
  try {
    const data = cache.get(number) || await get(`/api/games/${number}`);
    if (token !== requestId) return;
    cache.set(number, data); replay = data; selected = number; frame = 0; endWait = 0; playing = autoplay;
    $('game').value = String(number);
    $('left-name').textContent = names()[0]; $('right-name').textContent = names()[1];
    $('match-label').textContent = `GAME ${number}${demo.swap_sides ? ` · ${number % 2 ? 'FIRST ASSIGNMENT' : 'SWAPPED CHARACTERS'}` : ''}`;
    syncControls(); draw();
  } catch (error) { if (token === requestId) $('playback-status').textContent = error.message; }
}
function draw() {
  if (!assets || !replay) return;
  const index = Math.min(replay.frames.length, Math.floor(frame));
  const state = index ? replay.frames[index - 1] : replay.initial_state;
  ctx.drawImage(assets[0], 0, 0, 1000, 600);
  state.fighters.forEach((fighter, i) => {
    const size = i ? 250 : 162, scale = i ? 3 : 4, offset = i ? [112, 97] : [72, 46];
    const width = size * scale, x = fighter.x - offset[0] * scale, y = fighter.y - offset[1] * scale;
    ctx.save(); ctx.translate(x + (fighter.flip ? width : 0), y); ctx.scale(fighter.flip ? -1 : 1, 1);
    ctx.drawImage(assets[i + 1], fighter.frame_index * size, fighter.action * size, size, size, 0, 0, width, width);
    ctx.restore();
    const left = i ? 666 : 24;
    ctx.fillStyle = '#23232d'; ctx.fillRect(left, 52, 310, 20);
    ctx.fillStyle = i ? '#d773e6' : '#46bee6'; ctx.fillRect(left, 52, 310 * fighter.health / 100, 20);
    ctx.fillStyle = '#fff'; ctx.font = 'bold 24px Arial'; ctx.fillText(names()[i].toUpperCase(), left, 38);
    ctx.font = '18px Arial'; ctx.fillText(`HP ${fighter.health}`, left, 98);
  });
  ctx.fillStyle = '#fff'; ctx.font = 'bold 28px Arial';
  ctx.fillText(`${Math.max(0, (state.max_steps - state.step) / replay.fps).toFixed(1)}s`, 455, 45);
  const outcome = state.done ? (state.winner ? `${names()[state.winner - 1]} wins` : 'Draw') : 'VS';
  $('outcome').textContent = outcome;
  $('playback-status').textContent = state.done ? `${outcome} · ${state.reason.replaceAll('_', ' ')}` :
    `Game ${selected} · ${playing ? 'Playing' : 'Paused'} · ${speed}×`;
}
function animate(now) {
  const dt = lastTime ? Math.min((now - lastTime) / 1000, 0.1) : 0; lastTime = now;
  if (replay && playing) {
    frame = Math.min(replay.frames.length, frame + dt * replay.fps * speed);
    if (frame >= replay.frames.length) {
      endWait += dt;
      if (!$('auto').checked || selected >= (demo?.games_requested || 1)) playing = false;
      else if (endWait >= 2 && demo.games.some(game => game.number === selected + 1)) selectGame(selected + 1, true);
      else if (endWait >= 2) $('status').textContent = 'Waiting for the next game';
    }
    syncControls(); draw();
  }
  requestAnimationFrame(animate);
}
function renderReplies(data) {
  const key = JSON.stringify(data); if (key === replyKey) return; replyKey = key;
  const positions = [...$('replies').querySelectorAll('.reply-log')].map(log =>
    ({top: log.scrollTop, bottom: log.scrollHeight - log.scrollTop - log.clientHeight < 40}));
  const cards = data.agents.map(({agent, replies}) => {
    const card = element('article', undefined, 'reply-card'), top = element('div', undefined, 'reply-card-top');
    top.append(element('h3', agent.name), element('span', agent.status.replaceAll('_', ' '), 'badge'));
    card.append(top, element('p', `After game ${data.after_game} · Revision ${agent.revision || 0} · ${agent.test_cases || 0} input tests`, 'reply-meta'));
    const log = element('div', undefined, 'reply-log'); log.tabIndex = 0; log.setAttribute('aria-label', `${agent.name} replies`);
    if (!replies.length) log.append(element('p', 'Waiting for the first reply…'));
    for (const reply of replies) {
      const block = element('div', undefined, 'reply'); block.append(element('span', `REPLY ${reply.turn}`, 'tag'), element('p', reply.note));
      for (const call of reply.calls) {
        let detail = call.tool.replaceAll('_', ' ');
        if (call.error) detail += ` · Error: ${call.error}`;
        else if (call.tests) {
          const checked = call.tests.filter(test => test.matches_expected !== null);
          detail += ` · ${call.tests.length} inputs · ${checked.filter(test => test.matches_expected).length}/${checked.length} expected actions matched`;
        } else if (call.tool === 'edit_weights') detail += ` · ${call.updates} values set`;
        if (!call.done) detail += ' · requested';
        block.append(element('p', detail, call.error ? 'tool error' : 'tool'));
        if (call.reason) block.append(element('p', call.reason, 'tool-reason'));
      }
      log.append(block);
    }
    if (agent.error) log.append(element('p', agent.error, 'error'));
    if (agent.note) log.append(element('p', agent.note));
    card.append(log); return card;
  });
  $('replies').replaceChildren(...cards);
  cards.forEach((card, index) => {
    const log = card.querySelector('.reply-log'), old = positions[index];
    log.scrollTop = !old || old.bottom ? log.scrollHeight : old.top;
  });
}
async function poll() {
  if (polling || launching) return; polling = true;
  const version = generation;
  try {
    const data = await get('/api/run');
    if (version !== generation) return;
    if (data.run !== activeRun) resetRun(data.run);
    runToken = data.run_token;
    $('new-run').disabled = !data.can_start;
    $('run-games').disabled = !data.can_start;
    demo = data.demo;
    if (!demo) { $('status').textContent = 'Ready for a new run'; return; }
    updateTally();
    $('run-message').textContent = demo.error || (data.can_start ?
      'New run starts both agents with the same fresh random weights.' :
      'Run active · Characters switch each game · Both agents edit after each game');
    fallback = false; $('player').hidden = true; canvas.hidden = false; $('controls').hidden = false;
    $('mode-note').textContent = `${data.run} · Playback stays in this browser`;
    $('status').textContent = `${demo.games.length}/${demo.games_requested} games ready · ${demo.phase.replaceAll('_', ' ')}`;
    const ready = new Set(demo.games.map(game => game.number));
    const options = [...Array(demo.games_requested)].map((_, i) => {
      const option = element('option', `Game ${i + 1}${ready.has(i + 1) ? '' : ' · waiting'}`);
      option.value = i + 1; option.disabled = !ready.has(i + 1); return option;
    });
    if ($('game').options.length !== options.length || [...$('game').options].some((option, i) => option.disabled !== options[i].disabled)) $('game').replaceChildren(...options);
    $('game').value = selected; $('game').disabled = !ready.size;
    const rounds = [...new Set([...demo.edit_rounds.map(round => round.after_game), demo.editing_after_game].filter(Boolean))].sort((a,b) => a-b);
    const chosen = $('edit-round').value || 'latest';
    if ($('edit-round').options.length !== rounds.length + 1) {
      const latest = element('option', 'Latest · follow live'); latest.value = 'latest';
      $('edit-round').replaceChildren(latest, ...rounds.map(round => {
        const option = element('option', `After game ${round}`); option.value = round; return option;
      })); $('edit-round').value = chosen;
    }
    const after = chosen === 'latest' ? rounds.at(-1) : Number(chosen);
    if (after) {
      const replies = await get(`/api/replies?after=${after}`);
      if (version !== generation) return;
      renderReplies(replies);
    } else $('replies').textContent = 'The first edit round starts after game 1.';
    if (!replay && ready.has(1)) await selectGame(1, true);
    syncControls();
  } catch (error) {
    if (version !== generation) return;
    $('status').textContent = 'Connection unavailable · retrying';
    if (!demo && !fallback) {
      fallback = true; canvas.hidden = true; $('player').hidden = false; $('controls').hidden = true;
      $('player').src = `/live/${encodeURIComponent(match)}/?autoplay=true&muted=true&playsInline=true`;
      $('mode-note').textContent = 'Video stream · No replay run is configured';
    }
  } finally { polling = false; }
}
$('new-run').addEventListener('click', async () => {
  if (launching || !runToken) return;
  launching = true; ++generation; ++requestId;
  $('new-run').disabled = true; $('run-games').disabled = true;
  $('run-message').textContent = 'Starting a new run…';
  try {
    const response = await fetch('/api/runs', {method:'POST',
      headers:{'Content-Type':'application/json', 'X-Run-Token':runToken},
      body:JSON.stringify({games:Number($('run-games').value)}), signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error(response.status === 409 ? 'A run is already active.' : `Could not start the run (${response.status}).`);
    const data = await response.json(); resetRun(data.run);
    demo = {games:[], agents:[{name:'Astra'}, {name:'Fable'}]}; updateTally(); syncControls();
    $('run-message').textContent = 'New run started. Waiting for game 1…';
  } catch (error) {
    $('run-message').textContent = `${error.message} Check the run status before you try again.`;
  } finally { launching = false; poll(); }
});
$('play').addEventListener('click', () => {if (!replay) return; if (frame >= replay.frames.length) frame = 0; playing = !playing; endWait = 0; syncControls(); draw();});
$('restart').addEventListener('click', () => {frame = 0; endWait = 0; syncControls(); draw();});
$('game').addEventListener('change', () => selectGame(Number($('game').value), playing));
$('next').addEventListener('click', () => selectGame(selected + 1, playing));
$('speed').addEventListener('change', () => {speed = Number($('speed').value); draw();});
$('seek').addEventListener('input', () => {frame = Number($('seek').value); endWait = 0; syncControls(); draw();});
$('edit-round').addEventListener('change', () => {replyKey = ''; poll();});
$('reconnect').addEventListener('click', () => {if (fallback) $('player').src = $('player').src; poll();});
Promise.all(['/assets/background.jpg', '/assets/grimes-sprites.png', '/assets/shoggoth-sprites.png'].map(src => new Promise((resolve, reject) => {
  const image = new Image(); image.onload = () => resolve(image); image.onerror = reject; image.src = src;
}))).then(images => {assets = images; draw();}).catch(() => {$('playback-status').textContent = 'Game images could not load.';});
poll(); setInterval(poll, 1500); requestAnimationFrame(animate);
