class GameAudio {
  constructor(makeContext = () => new (window.AudioContext || window.webkitAudioContext)()) {
    this.makeContext = makeContext;
    this.context = null; this.buffer = null; this.source = null;
    this.muted = false; this.error = ''; this.loadId = 0;
  }
  async unlock() {
    try {
      this.context ||= this.makeContext();
      await this.context.resume();
    } catch (_) { this.error = 'Audio unavailable'; }
  }
  stop() {
    if (this.source) { this.source.stop(); this.source.disconnect(); this.source = null; }
  }
  reset() {
    ++this.loadId; this.abort?.abort(); this.stop(); this.buffer = null; this.error = '';
  }
  async load(url) {
    this.reset();
    const id = this.loadId;
    if (!url) { this.error = 'No audio track'; return; }
    const controller = this.abort = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      this.context ||= this.makeContext();
      const response = await fetch(url, {signal:controller.signal});
      if (!response.ok) throw new Error('Audio unavailable');
      const decoded = await this.context.decodeAudioData(await response.arrayBuffer());
      if (id === this.loadId) this.buffer = decoded;
    } catch (_) { if (id === this.loadId) this.error = 'Audio unavailable'; }
    finally { clearTimeout(timeout); }
  }
  sync(time, playing, speed) {
    if (!playing || speed !== 1 || this.muted || !this.buffer ||
        this.context?.state !== 'running' || time >= this.buffer.duration) { this.stop(); return; }
    if (this.source && Math.abs(this.offset + this.context.currentTime - this.started - time) < .08) return;
    this.stop();
    this.source = this.context.createBufferSource();
    this.source.buffer = this.buffer; this.source.connect(this.context.destination);
    this.offset = Math.max(0, time); this.started = this.context.currentTime;
    this.source.start(0, this.offset);
  }
}
if (typeof module !== 'undefined') module.exports = {GameAudio};
