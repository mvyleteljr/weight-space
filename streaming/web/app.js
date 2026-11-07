const params = new URLSearchParams(location.search);
const requested = params.get('match') || 'match-1';
const match = /^match-[a-zA-Z0-9_-]+$/.test(requested) ? requested : 'match-1';
const base = `/live/${encodeURIComponent(match)}/`;
const player = document.getElementById('player');
const status = document.getElementById('status');
document.getElementById('match-label').textContent = match.replaceAll('-', ' ').toUpperCase();
function connect() {
  player.src = `${base}?autoplay=true&muted=true&playsInline=true`;
}
document.getElementById('reconnect').addEventListener('click', connect);
connect();
async function checkStream() {
  try {
    const response = await fetch(`${base}index.m3u8`, {cache:'no-store', signal:AbortSignal.timeout(5000)});
    status.textContent = response.ok ? '● Stream available' : '○ Waiting for match';
  } catch {
    status.textContent = '○ Reconnecting';
  }
  setTimeout(checkStream, 5000);
}
checkStream();
