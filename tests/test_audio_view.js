const assert = require('node:assert/strict');
const {GameAudio}=require('../streaming/web/audio.js');
(async () => {
  const sources=[];
  const context={state:'suspended',currentTime:0,destination:{},
    resume:async()=>{context.state='running';},
    createBufferSource:()=>{const source={connect(){},disconnect(){},stop(){this.stopped=true;},start(_,offset){this.offset=offset;}};sources.push(source);return source;}};
  const audio=new GameAudio(()=>context);
  await audio.unlock(); audio.buffer={duration:30};
  audio.sync(2,true,1); assert.equal(sources[0].offset,2);
  context.currentTime=.05; audio.sync(2.05,true,1); assert.equal(sources.length,1);
  audio.sync(2.1,true,2); assert.equal(audio.source,null); assert.ok(sources[0].stopped);
  audio.sync(8,true,1); assert.equal(sources[1].offset,8); // returning to 1× resumes at displayed time
  audio.muted=true; audio.sync(8.1,true,1); assert.equal(audio.source,null);
  audio.muted=false; audio.sync(8.2,false,1); assert.equal(audio.source,null);
  audio.sync(10,true,1); assert.equal(sources[2].offset,10);
  audio.sync(20,true,1); assert.equal(sources[3].offset,20); assert.ok(sources[2].stopped);
  audio.sync(30,true,1); assert.equal(audio.source,null);
  audio.reset(); assert.equal(audio.buffer,null);
  console.log('Audio playback timing, pause, mute and speed tests passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
